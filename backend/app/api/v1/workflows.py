"""Workflow orchestration API routes (`API.md §6.4`, `Architecture.md §4`)."""

from __future__ import annotations

import datetime
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.deps import get_current_principal, get_db
from app.core.errors import NotFoundError, UnprocessableEntityError
from app.models.enums import ActorType, WorkflowStatus
from app.models.project import Project
from app.models.spec import APISpec
from app.models.workflow import ToolCall, WorkflowCheckpoint, WorkflowRun
from app.rbac.enforce import load_project_for_principal, require_project_permission
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
from app.workflows.orchestrator import Orchestrator
from app.workflows.state import WorkflowState

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
) -> TriggerWorkflowResponse:
    """Trigger multi-agent orchestration for a project."""
    # Find latest spec if available
    spec = await session.scalar(
        select(APISpec)
        .where(APISpec.project_id == project.id)
        .order_by(APISpec.created_at.desc())
        .limit(1)
    )

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
        actor_type=ActorType.USER,
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
    }

    # Execute workflow in background task
    engine_session_factory = async_sessionmaker(
        bind=session.bind, class_=AsyncSession, expire_on_commit=False
    )
    orchestrator = Orchestrator(engine_session_factory)
    background_tasks.add_task(orchestrator.run, run.id, initial_state)

    return TriggerWorkflowResponse(workflow_run_id=run.id, status=WorkflowStatus.QUEUED)


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

    # Multi-tenant check
    await load_project_for_principal(session, principal, run.project_id)

    # Get latest checkpoint for current node
    latest_checkpoint = await session.scalar(
        select(WorkflowCheckpoint)
        .where(WorkflowCheckpoint.workflow_run_id == run.id)
        .order_by(WorkflowCheckpoint.created_at.desc())
        .limit(1)
    )

    current_node = latest_checkpoint.node_name if latest_checkpoint else None
    progress = 100 if run.status == WorkflowStatus.COMPLETED else (50 if current_node else 0)

    return WorkflowRunResponse(
        id=run.id,
        status=run.status,
        current_node=current_node,
        progress_percent=progress,
        started_at=run.started_at,
        completed_at=run.completed_at,
        total_tokens_used=run.total_tokens_used,
    )


@router.post("/workflows/{run_id}/approve", response_model=ApproveWorkflowResponse)
async def approve_workflow_gate(
    run_id: uuid.UUID,
    payload: ApproveWorkflowRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
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

    run.status = WorkflowStatus.RUNNING if payload.approved else WorkflowStatus.FAILED
    await session.flush()

    await audit_service.record(
        session,
        action="workflow.gate_approved" if payload.approved else "workflow.gate_rejected",
        actor_type=ActorType.USER,
        organization_id=project.organization_id,
        resource_type="workflow_run",
        resource_id=str(run.id),
        metadata={"notes": payload.notes, "approved": payload.approved},
    )

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
) -> dict[str, str]:
    """Cancel an in-progress workflow run."""
    run = await session.get(WorkflowRun, run_id)
    if run is None:
        raise NotFoundError("Workflow run not found.")

    project = await load_project_for_principal(session, principal, run.project_id)

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

    await load_project_for_principal(session, principal, run.project_id)

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
