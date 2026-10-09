"""Workflow orchestration API routes (`API.md §6.4`, `Architecture.md §4`)."""

from __future__ import annotations

import datetime
import uuid

import redis.asyncio as aioredis
from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.constants import DEFAULT_TARGET_LANGUAGES
from app.core.deps import get_current_principal, get_db, get_redis
from app.core.errors import ConflictError, NotFoundError, UnprocessableEntityError
from app.core.logging import get_logger
from app.core.metrics import pipeline_error_total
from app.models.enums import ActorType, WorkflowStatus
from app.models.project import Project
from app.models.spec import APISpec
from app.models.workflow import ToolCall, WorkflowCheckpoint, WorkflowRun
from app.rbac.enforce import (
    assert_project_permission,
    load_project_for_principal,
    require_project_permission,
)
from app.rbac.policy import Permission, Principal
from app.schemas.workflow import (
    ApproveWorkflowRequest,
    ApproveWorkflowResponse,
    ToolCallResponse,
    TriggerWorkflowRequest,
    TriggerWorkflowResponse,
    WorkflowRunResponse,
)
from app.services import audit_service
from app.workflows.dispatch import dispatch_run
from app.workflows.state import WorkflowState

logger = get_logger(__name__)

# Stages that run after the human approval gate, in pipeline order.
_POST_PLAN_STAGES = ("generate", "test", "export")

router = APIRouter(tags=["workflows"])


@router.post(
    "/projects/{id}/workflows",
    response_model=TriggerWorkflowResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_workflow(
    payload: TriggerWorkflowRequest,
    background_tasks: BackgroundTasks,
    project: Project = Depends(require_project_permission(Permission.WORKFLOW_TRIGGER)),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> TriggerWorkflowResponse:
    """Trigger multi-agent orchestration for a project."""
    # Find latest spec if available
    spec = await session.scalar(
        select(APISpec)
        .where(APISpec.project_id == project.id)
        .order_by(APISpec.created_at.desc())
        .limit(1)
    )

    # Supersede any active or paused runs for this project
    stale_runs = (
        await session.scalars(
            select(WorkflowRun).where(
                WorkflowRun.project_id == project.id,
                WorkflowRun.status.in_([
                    WorkflowStatus.RUNNING,
                    WorkflowStatus.QUEUED,
                    WorkflowStatus.PAUSED_FOR_APPROVAL,
                ]),
            )
        )
    ).all()
    for stale in stale_runs:
        stale.status = WorkflowStatus.CANCELLED
        # Superseded: cancelled by the newer run, finished now.
        stale.completed_at = stale.completed_at or datetime.datetime.now(datetime.UTC)

    run = WorkflowRun(
        project_id=project.id,
        triggered_by=principal.user_id,
        status=WorkflowStatus.QUEUED,
    )
    session.add(run)
    await session.flush()

    await audit_service.record(
        session,
        action="workflow.triggered",
        **audit_service.actor(principal),
        organization_id=project.organization_id,
        resource_type="workflow_run",
        resource_id=str(run.id),
        metadata={"stages": payload.stages, "target_languages": payload.target_languages},
    )

    initial_state: WorkflowState = {
        "project_id": str(project.id),
        "organization_id": str(project.organization_id),
        "workflow_run_id": str(run.id),
        "stages": payload.stages,
        "target_languages": payload.target_languages,
        "normalized_spec": spec.raw_normalized if spec else None,
        "generated_files": [],
        "test_suite": [],
        "errors": [],
        "token_budget": getattr(project, "token_budget", None) or settings.default_token_budget,
    }

    # Commit before dispatching so the worker (or background task) sees every row.
    await session.commit()
    await dispatch_run(
        run_id=run.id,
        state=initial_state,
        settings=settings,
        session=session,
        background_tasks=background_tasks,
        redis_client=redis_client,
        requested_mode=payload.execution_mode,
    )

    return TriggerWorkflowResponse(workflow_run_id=run.id, status=WorkflowStatus.QUEUED)


@router.get("/workflows", response_model=list[WorkflowRunResponse])
async def list_workflows(
    project_id: uuid.UUID = Query(...),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[WorkflowRunResponse]:
    """List workflow runs for a project."""
    await assert_project_permission(session, principal, Permission.WORKFLOW_READ, project_id)
    stmt = (
        select(WorkflowRun)
        .where(WorkflowRun.project_id == project_id)
        .order_by(WorkflowRun.created_at.desc(), WorkflowRun.id.desc())
        .limit(limit)
    )
    runs = list((await session.execute(stmt)).scalars().all())
    return [await _run_to_response(run, session) for run in runs]


async def _run_to_response(run: WorkflowRun, session: AsyncSession) -> WorkflowRunResponse:
    latest_checkpoint = await session.scalar(
        select(WorkflowCheckpoint)
        .where(WorkflowCheckpoint.workflow_run_id == run.id)
        .order_by(WorkflowCheckpoint.created_at.desc())
        .limit(1)
    )
    current_node = run.current_node or (latest_checkpoint.node_name if latest_checkpoint else None)

    if run.status == WorkflowStatus.COMPLETED:
        progress = 100
    elif run.progress_percent and run.progress_percent > 0:
        progress = run.progress_percent
    elif (
        latest_checkpoint
        and isinstance(latest_checkpoint.state_snapshot, dict)
        and latest_checkpoint.state_snapshot.get("progress_percent") is not None
    ):
        progress = int(latest_checkpoint.state_snapshot.get("progress_percent", 0))
    else:
        settings = get_settings()
        progress = settings.workflow_node_progress_map.get(current_node, run.progress_percent or 0)

    return WorkflowRunResponse(
        id=run.id,
        status=run.status,
        current_node=current_node,
        progress_percent=progress,
        started_at=run.started_at,
        completed_at=run.completed_at,
        total_tokens_used=run.total_tokens_used,
    )


@router.get("/workflows/{run_id}", response_model=WorkflowRunResponse)
async def get_workflow_run(
    run_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> WorkflowRunResponse:
    """Get the current progress and status of a workflow run."""
    run = await session.get(WorkflowRun, run_id)
    if run is None:
        raise NotFoundError("Workflow run not found.")

    # Tenant isolation and the project role: org membership alone is not enough.
    await assert_project_permission(session, principal, Permission.WORKFLOW_READ, run.project_id)

    return await _run_to_response(run, session)


@router.post("/workflows/{run_id}/approve", response_model=ApproveWorkflowResponse)
async def approve_workflow_gate(
    run_id: uuid.UUID,
    payload: ApproveWorkflowRequest,
    background_tasks: BackgroundTasks,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> ApproveWorkflowResponse:
    """Approve a human-in-the-loop gate before generated code runs."""
    run = await session.get(WorkflowRun, run_id)
    if run is None:
        raise NotFoundError("Workflow run not found.")

    project = await load_project_for_principal(session, principal, run.project_id)

    # Human-in-the-loop approval requires WORKFLOW_APPROVE (Project Owner)
    from app.rbac.enforce import resolve_project_role
    from app.rbac.policy import PERMISSIONS, project_role_satisfies
    actual_role = await resolve_project_role(session, principal, project)
    req = PERMISSIONS[Permission.WORKFLOW_APPROVE]
    if req.project_role and not project_role_satisfies(actual_role, req.project_role):
        from app.core.errors import ForbiddenError
        raise ForbiddenError("Only project owners can approve workflow gates.")

    if run.status != WorkflowStatus.PAUSED_FOR_APPROVAL:
        raise UnprocessableEntityError("Workflow is not waiting for approval.")

    latest_checkpoint: WorkflowCheckpoint | None = None
    if payload.approved:
        latest_checkpoint = await session.scalar(
            select(WorkflowCheckpoint)
            .where(WorkflowCheckpoint.workflow_run_id == run.id)
            .order_by(WorkflowCheckpoint.created_at.desc())
            .limit(1)
        )
        if latest_checkpoint is None:
            raise UnprocessableEntityError("Workflow has no checkpoint to resume from.")

    # Claim the gate atomically: two concurrent approvals both saw PAUSED above, and
    # each started a resume orchestrator. Only the request that flips the row proceeds.
    new_status = WorkflowStatus.RUNNING if payload.approved else WorkflowStatus.FAILED
    claimed = await session.execute(
        update(WorkflowRun)
        .where(WorkflowRun.id == run.id, WorkflowRun.status == WorkflowStatus.PAUSED_FOR_APPROVAL)
        .values(status=new_status)
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:
        raise ConflictError("This approval gate was already answered.")
    run.status = new_status

    await audit_service.record(
        session,
        action="workflow.gate_approved" if payload.approved else "workflow.gate_rejected",
        **audit_service.actor(principal),
        organization_id=project.organization_id,
        resource_type="workflow_run",
        resource_id=str(run.id),
        metadata={"notes": payload.notes, "approved": payload.approved},
    )

    if payload.approved:
        resume_state = dict(latest_checkpoint.state_snapshot)
        resume_state["plan_approved"] = True
        if payload.target_languages:
            resume_state["target_languages"] = payload.target_languages
        elif not resume_state.get("target_languages"):
            resume_state["target_languages"] = list(DEFAULT_TARGET_LANGUAGES)
        if (resume_state.get("test_run_summary") or {}).get("failed", 0) > 0 and len(resume_state.get("repair_attempts", [])) >= 3:
            # The owner reviewed the failing tests and chose to export regardless.
            resume_state["stages"] = ["export"]
            resume_state["export_override_approved"] = True
        else:
            # Resume with the stages the caller asked for after planning. Overwriting
            # them made a ["plan", "generate"] run also test and run every export
            # packager. A run that requested nothing past "plan" (the upload auto-plan)
            # means "approve and build", so it gets the full post-plan pipeline.
            requested = [
                s for s in (resume_state.get("stages") or []) if s in _POST_PLAN_STAGES
            ]
            resume_state["stages"] = requested or list(_POST_PLAN_STAGES)

        await session.commit()
        await dispatch_run(
            run_id=run.id,
            state=resume_state,
            settings=settings,
            session=session,
            background_tasks=background_tasks,
            redis_client=redis_client,
        )
    else:
        await session.commit()

    return ApproveWorkflowResponse(
        workflow_run_id=run.id,
        status=run.status,
        approved=payload.approved,
    )


@router.post("/workflows/{run_id}/cancel", status_code=status.HTTP_200_OK)
async def cancel_workflow_run(
    run_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> dict[str, str]:
    """Cancel an in-progress workflow run."""
    run = await session.get(WorkflowRun, run_id)
    if run is None:
        raise NotFoundError("Workflow run not found.")

    project = await assert_project_permission(
        session, principal, Permission.WORKFLOW_CANCEL, run.project_id
    )

    if run.status in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED):
        return {"status": run.status, "message": "Workflow already terminated."}

    run.status = WorkflowStatus.CANCELLED
    run.completed_at = datetime.datetime.now(datetime.UTC)
    await session.flush()

    await audit_service.record(
        session,
        action="workflow.cancelled",
        actor_type=ActorType.USER,
        organization_id=project.organization_id,
        resource_type="workflow_run",
        resource_id=str(run.id),
    )

    try:
        from app.workflows.event_recorder import record_agent_event
        await record_agent_event(
            session,
            workflow_run_id=run.id,
            agent_name="orchestrator",
            event_type="workflow_finished",
            payload={"status": "cancelled", "reason": "user_cancelled"},
        )
        await session.flush()
    except Exception as exc:
        pipeline_error_total.labels(subsystem="workflow_cancel_audit", error_type=type(exc).__name__).inc()
        logger.error("cancel_audit_event_failed", run_id=str(run.id), error=str(exc), exc_info=True)

    try:
        from app.services.event_publisher import EventPublisher
        event_pub = EventPublisher(redis_client)
        await event_pub.publish_workflow_completed(
            run_id=str(run.id),
            project_id=str(run.project_id),
            status=WorkflowStatus.CANCELLED.value,
        )
    except Exception as exc:
        pipeline_error_total.labels(subsystem="workflow_cancel_event", error_type=type(exc).__name__).inc()
        logger.error("cancel_event_publish_failed", run_id=str(run.id), error=str(exc), exc_info=True)

    return {"status": WorkflowStatus.CANCELLED, "message": "Workflow cancelled."}


@router.get("/workflows/{run_id}/tool-calls", response_model=list[ToolCallResponse])
async def list_workflow_tool_calls(
    run_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[ToolCallResponse]:
    """List tool call traces for a workflow run."""
    run = await session.get(WorkflowRun, run_id)
    if run is None:
        raise NotFoundError("Workflow run not found.")

    await assert_project_permission(session, principal, Permission.WORKFLOW_READ, run.project_id)

    # Fetch tool calls associated with events in this workflow run
    from app.models.workflow import AgentEvent
    stmt = (
        select(ToolCall)
        .join(AgentEvent, ToolCall.agent_event_id == AgentEvent.id)
        .where(AgentEvent.workflow_run_id == run.id)
        .limit(limit)
    )
    rows = list((await session.execute(stmt)).scalars())
    return [
        ToolCallResponse(
            id=row.id,
            agent_event_id=row.agent_event_id,
            tool_name=row.tool_name,
            arguments=row.arguments,
            result=row.result,
            duration_ms=row.duration_ms,
        )
        for row in rows
    ]
