"""Testing API routes (`API.md §6.7`, `Feature.md §13-14`)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_principal, get_db
from app.core.errors import NotFoundError
from app.models.enums import ActorType, TestEnvironment
from app.models.project import Project
from app.models.testing import TestRun, TestResult
from app.rbac.enforce import load_project_for_principal, require_project_permission
from app.rbac.policy import Permission, Principal
from app.schemas.testing import TestRequest, TestRunResponse, TestResultResponse, RepairAttemptResponse, TestRunSummaryResponse
from app.services import audit_service
from app.workflows.orchestrator import Orchestrator
from app.workflows.state import WorkflowState

router = APIRouter(prefix="/projects", tags=["testing"])


@router.post("/{id}/test", response_model=TestRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_test(
    project_id: uuid.UUID,
    payload: TestRequest,
    background_tasks: BackgroundTasks,
    principal: Principal = Depends(require_project_permission(Permission.TEST_RUN)),
    session: AsyncSession = Depends(get_db),
) -> TestRunResponse:
    """Trigger tests for a project."""
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFoundError("Project not found.")

    # Validate environment
    env = payload.environment
    if env not in (TestEnvironment.SANDBOX.value, TestEnvironment.LIVE.value):
        from app.core.errors import UnprocessableEntityError
        raise UnprocessableEntityError(f"Invalid environment: {env}. Must be 'sandbox' or 'live'.")

    # Create test run
    test_run = TestRun(
        project_id=project.id,
        environment=env,
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

    # Execute tests in background
    engine_session_factory = __import__("sqlalchemy.ext.asyncio", fromlist=["async_sessionmaker"]).async_sessionmaker(
        bind=session.bind, class_=AsyncSession, expire_on_commit=False
    )
    orchestrator = Orchestrator(engine_session_factory)

    # For now, use a simple workflow state to trigger testing
    initial_state: WorkflowState = {
        "project_id": str(project.id),
        "organization_id": str(project.organization_id),
        "workflow_run_id": str(test_run.id),
        "stages": ["test"],
        "target_languages": ["python", "node"],
        "generated_files": [],
        "test_suite": [],
        "errors": [],
    }

    background_tasks.add_task(orchestrator.run, test_run.id, initial_state)

    return TestRunResponse(test_run_id=test_run.id, status="running")


@router.get("/{id}/test-runs/{run_id}", response_model=TestRunSummaryResponse)
async def get_test_run(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    principal: Principal = Depends(require_project_permission(Permission.TEST_READ)),
    session: AsyncSession = Depends(get_db),
) -> TestRunSummaryResponse:
    """Get a test run with results and summary."""
    project = await load_project_for_principal(session, principal, project_id)

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

    return TestRunSummaryResponse(
        test_run_id=test_run.id,
        status="completed",
        summary={
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
        },
        results=result_responses,
    )


@router.get("/{id}/test-runs/{run_id}/repairs", response_model=list[RepairAttemptResponse])
async def list_repair_attempts(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    principal: Principal = Depends(require_project_permission(Permission.TEST_READ)),
    session: AsyncSession = Depends(get_db),
) -> list[RepairAttemptResponse]:
    """List repair attempts for a test run."""
    project = await load_project_for_principal(session, principal, project_id)

    # Get test results for this run
    results = list((await session.execute(
        select(TestResult).where(TestResult.test_run_id == run_id)
    )).scalars())

    result_ids = [r.id for r in results]
    if not result_ids:
        return []

    from app.models.testing import RepairAttempt
    repairs = list((await session.execute(
        select(RepairAttempt).where(RepairAttempt.test_result_id.in_(result_ids))
    )).scalars())

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