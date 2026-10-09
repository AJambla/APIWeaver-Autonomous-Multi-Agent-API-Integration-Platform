"""Testing API routes (`API.md §6.7`, `Feature.md §13-14`)."""

from __future__ import annotations

import uuid

import redis.asyncio as aioredis
from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.constants import DEFAULT_TARGET_LANGUAGES
from app.core.deps import get_current_principal, get_db, get_redis
from app.core.errors import NotFoundError, UnprocessableEntityError
from app.models.enums import ActorType, TestEnvironment, WorkflowStatus
from app.models.project import Project
from app.models.testing import RepairAttempt, TestResult, TestRun
from app.models.workflow import WorkflowRun
from app.rbac.enforce import require_project_permission
from app.rbac.policy import Permission, Principal
from app.schemas.testing import (
    RepairAttemptResponse,
    TestRequest,
    TestResultResponse,
    TestRunResponse,
    TestRunSummaryResponse,
)
from app.services import audit_service
from app.services.workflow_input_service import (
    load_generated_files,
    load_normalized_spec,
)
from app.workflows.dispatch import dispatch_run
from app.workflows.state import WorkflowState

router = APIRouter(prefix="/projects", tags=["testing"])


@router.post("/{id}/test", response_model=TestRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_test(
    payload: TestRequest,
    background_tasks: BackgroundTasks,
    project: Project = Depends(require_project_permission(Permission.TEST_RUN)),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> TestRunResponse:
    """Trigger tests for a project."""
    # Validate environment
    env = payload.environment
    if env not in (TestEnvironment.SANDBOX.value, TestEnvironment.LIVE.value):
        raise UnprocessableEntityError(f"Invalid environment: {env}. Must be 'sandbox' or 'live'.")
    if env == TestEnvironment.LIVE.value and not settings.sandbox_live_network_enabled:
        # Live tests give generated code network access to the target API.
        raise UnprocessableEntityError(
            "Live testing is disabled on this deployment (SANDBOX_LIVE_NETWORK_ENABLED=false)."
        )

    # The orchestrator writes agent events keyed by workflow run, so this stage needs a
    # real WorkflowRun row rather than the TestRun's own id.
    run = WorkflowRun(
        project_id=project.id,
        triggered_by=principal.user_id,
        status=WorkflowStatus.QUEUED,
    )
    session.add(run)
    await session.flush()

    # Create test run
    test_run = TestRun(
        project_id=project.id,
        workflow_run_id=run.id,
        environment=env,
        status="running",
    )
    session.add(test_run)
    await session.flush()

    await audit_service.record(
        session,
        action="test.triggered",
        actor_type=ActorType.USER,
        organization_id=project.organization_id,
        resource_type="test_run",
        resource_id=str(test_run.id),
        metadata={"environment": env, "endpoint_ids": [str(eid) for eid in (payload.endpoint_ids or [])]},
    )
    await session.commit()

    # Execute tests in background
    engine_session_factory = async_sessionmaker(
        bind=session.bind, class_=AsyncSession, expire_on_commit=False
    )
    # Testing is a single-stage run: the spec and the generated client have to come back
    # out of the database, because this request never passed through the earlier stages.
    async with engine_session_factory() as hydrate_session:
        normalized_spec = await load_normalized_spec(hydrate_session, project.id)
        generated_files = await load_generated_files(hydrate_session, project.id)

    initial_state: WorkflowState = {
        "project_id": str(project.id),
        "organization_id": str(project.organization_id),
        "workflow_run_id": str(run.id),
        "environment": env,
        "stages": ["test"],
        "target_languages": list(DEFAULT_TARGET_LANGUAGES),
        "normalized_spec": normalized_spec,
        "generated_files": generated_files,
        "test_suite": [],
        "errors": [],
    }

    await dispatch_run(
        run_id=run.id,
        state=initial_state,
        settings=settings,
        session=session,
        background_tasks=background_tasks,
        redis_client=redis_client,
        post_run={"kind": "test", "test_run_id": str(test_run.id)},
    )

    return TestRunResponse(test_run_id=test_run.id, status="running")


async def _repairs_for(
    session: AsyncSession, result_ids: list[uuid.UUID]
) -> list[RepairAttemptResponse]:
    """Read the self-healing loop recorded against these results."""
    if not result_ids:
        return []
    repairs = await session.scalars(
        select(RepairAttempt)
        .where(RepairAttempt.test_result_id.in_(result_ids))
        .order_by(RepairAttempt.attempt_number)
    )
    return [
        RepairAttemptResponse(
            id=r.id,
            test_result_id=r.test_result_id,
            attempt_number=r.attempt_number,
            failure_classification=r.failure_classification,
            diff_summary=r.diff_summary,
            outcome=r.outcome,
        )
        for r in repairs
    ]


@router.get("/{id}/test-runs/latest", response_model=TestRunSummaryResponse)
async def get_latest_test_run(
    project: Project = Depends(require_project_permission(Permission.TEST_READ)),
    session: AsyncSession = Depends(get_db),
) -> TestRunSummaryResponse:
    """Get the latest test run with results and summary for a project."""
    test_run = await session.scalar(
        select(TestRun)
        .where(TestRun.project_id == project.id)
        .order_by(TestRun.started_at.desc())
        .limit(1)
    )
    if test_run is None:
        raise NotFoundError("No test runs found for this project.")

    results = list((await session.execute(
        select(TestResult).where(TestResult.test_run_id == test_run.id)
    )).scalars())

    result_responses = [
        TestResultResponse(
            id=r.id,
            test_run_id=r.test_run_id,
            endpoint_id=r.endpoint_id,
            status=r.status,
            status_code=r.status_code,
            latency_ms=r.latency_ms,
            error=r.response_snapshot.get("error") if r.response_snapshot else None,
            response_snapshot=r.response_snapshot,
            stack_trace=r.response_snapshot.get("stack_trace") if r.response_snapshot else None,
        )
        for r in results
    ]

    passed = sum(1 for r in results if r.status == "passed")
    failed = sum(1 for r in results if r.status == "failed")
    skipped = sum(1 for r in results if r.status == "skipped")

    stored_summary = test_run.summary or {}
    errors = [str(error) for error in (stored_summary.get("errors") or [])]

    return TestRunSummaryResponse(
        test_run_id=test_run.id,
        status=test_run.status,
        summary={
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
        },
        results=result_responses,
        errors=errors,
        repairs=await _repairs_for(session, [r.id for r in results]),
    )


@router.get("/{id}/test-runs/{run_id}", response_model=TestRunSummaryResponse)
async def get_test_run(
    run_id: uuid.UUID,
    project: Project = Depends(require_project_permission(Permission.TEST_READ)),
    session: AsyncSession = Depends(get_db),
) -> TestRunSummaryResponse:
    """Get a test run with results and summary."""
    test_run = await session.get(TestRun, run_id)
    if test_run is None or test_run.project_id != project.id:
        raise NotFoundError("Test run not found.")

    results = list((await session.execute(
        select(TestResult).where(TestResult.test_run_id == run_id)
    )).scalars())

    result_responses = [
        TestResultResponse(
            id=r.id,
            test_run_id=r.test_run_id,
            endpoint_id=r.endpoint_id,
            status=r.status,
            status_code=r.status_code,
            latency_ms=r.latency_ms,
            error=r.response_snapshot.get("error") if r.response_snapshot else None,
            response_snapshot=r.response_snapshot,
            stack_trace=r.response_snapshot.get("stack_trace") if r.response_snapshot else None,
        )
        for r in results
    ]

    passed = sum(1 for r in results if r.status == "passed")
    failed = sum(1 for r in results if r.status == "failed")
    skipped = sum(1 for r in results if r.status == "skipped")

    stored_summary = test_run.summary or {}
    errors = [str(error) for error in (stored_summary.get("errors") or [])]

    return TestRunSummaryResponse(
        test_run_id=test_run.id,
        status=test_run.status,
        summary={
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
        },
        results=result_responses,
        errors=errors,
        repairs=await _repairs_for(session, [r.id for r in results]),
    )


@router.get("/{id}/test-runs/{run_id}/repairs", response_model=list[RepairAttemptResponse])
async def list_repair_attempts(
    run_id: uuid.UUID,
    project: Project = Depends(require_project_permission(Permission.TEST_READ)),
    session: AsyncSession = Depends(get_db),
) -> list[RepairAttemptResponse]:
    """List repair attempts for a test run."""
    # Get test results for this run, but only if the run belongs to this project.
    results = list((await session.execute(
        select(TestResult)
        .join(TestRun, TestResult.test_run_id == TestRun.id)
        .where(TestResult.test_run_id == run_id, TestRun.project_id == project.id)
    )).scalars())

    return await _repairs_for(session, [r.id for r in results])