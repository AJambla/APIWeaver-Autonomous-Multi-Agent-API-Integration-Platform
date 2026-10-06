"""Export API routes (`API.md §6.8`, `Feature.md §15-24`)."""

from __future__ import annotations

import uuid

import redis.asyncio as aioredis
from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.deps import get_current_principal, get_db, get_redis
from app.models.enums import ActorType, ExportType, WorkflowStatus
from app.models.export import Export
from app.models.project import Project
from app.models.workflow import WorkflowRun
from app.rbac.enforce import require_project_permission
from app.rbac.policy import Permission, Principal
from app.schemas.export import ExportRequest, ExportResponse, MCPExportResponse
from sqlalchemy import select
from app.services import audit_service
from app.services.event_publisher import EventPublisher
from app.services.workflow_input_service import (
    load_generated_files,
    load_latest_test_results,
    load_normalized_spec,
)
from app.workflows.agents.export_agent import ExportAgent
from app.workflows.langgraph_pipeline import LangGraphOrchestrator
from app.workflows.state import WorkflowState

router = APIRouter(prefix="/projects", tags=["export"])


@router.post("/{id}/export", response_model=ExportResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_export(
    payload: ExportRequest,
    background_tasks: BackgroundTasks,
    project: Project = Depends(require_project_permission(Permission.EXPORT_CREATE)),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> ExportResponse:
    """Trigger artifact exports for a project."""
    # Create export record
    export_types = payload.export_types or [e.value for e in ExportType]
    artifacts_meta = []

    run = WorkflowRun(
        project_id=project.id,
        triggered_by=principal.user_id,
        status=WorkflowStatus.QUEUED,
    )
    session.add(run)
    await session.flush()

    export_ids: dict[str, uuid.UUID] = {}
    for export_type in export_types:
        exp = Export(
            project_id=project.id,
            export_type=export_type,
            status="queued",
        )
        session.add(exp)
        await session.flush()
        export_ids[export_type] = exp.id
        artifacts_meta.append({
            "export_id": str(exp.id),
            "type": export_type,
            "status": "queued",
        })

    await audit_service.record(
        session,
        action="export.triggered",
        actor_type=ActorType.USER,
        organization_id=project.organization_id,
        resource_type="export",
        resource_id=str(project.id),
        metadata={"export_types": export_types, "github_repo_name": payload.github_repo_name},
    )
    await session.commit()

    # Run export in background
    engine_session_factory = async_sessionmaker(
        bind=session.bind, class_=AsyncSession, expire_on_commit=False
    )
    orchestrator = LangGraphOrchestrator(
        session_factory=engine_session_factory,
        event_publisher=EventPublisher(redis_client),
    )

    # Export is a single-stage run: everything it packages has to be reloaded, because
    # this request did not pass through generation or testing.
    async with engine_session_factory() as hydrate_session:
        normalized_spec = await load_normalized_spec(hydrate_session, project.id)
        generated_files = await load_generated_files(hydrate_session, project.id)
        test_suite, test_run_summary = await load_latest_test_results(hydrate_session, project.id)

    initial_state: WorkflowState = {
        "project_id": str(project.id),
        "organization_id": str(project.organization_id),
        "workflow_run_id": str(run.id),
        "stages": ["export"],
        "target_languages": ["python", "node"],
        "normalized_spec": normalized_spec,
        "generated_files": generated_files,
        "test_suite": test_suite,
        "test_run_summary": test_run_summary,
        "export_types": export_types,
        "errors": [],
    }

    background_tasks.add_task(
        _execute_export_run, orchestrator, run.id, initial_state, engine_session_factory, export_ids
    )

    return ExportResponse(export_id=run.id, artifacts=artifacts_meta)


async def _execute_export_run(
    orchestrator: LangGraphOrchestrator,
    run_id: uuid.UUID,
    initial_state: WorkflowState,
    session_factory: async_sessionmaker[AsyncSession],
    export_ids: dict[str, uuid.UUID],
) -> WorkflowState:
    """Run the export stage, then give every queued `Export` row a terminal status."""
    state = await orchestrator.run(run_id, initial_state)

    artifacts = {
        str(a.get("type")): a for a in (state.get("exports") or []) if isinstance(a, dict)
    }

    async with session_factory() as session:
        for export_type, export_id in export_ids.items():
            artifact = artifacts.get(export_type)
            export = await session.get(Export, export_id)
            if export is None:
                continue
            if artifact is None:
                export.status = "failed"
                continue
            export.status = "failed" if artifact.get("status") == "failed" else "completed"
        await session.commit()
    return state


@router.post("/{id}/export/mcp", response_model=MCPExportResponse)
async def export_mcp(
    project: Project = Depends(require_project_permission(Permission.EXPORT_CREATE)),
    session: AsyncSession = Depends(get_db),
) -> MCPExportResponse:
    """Export MCP tools for a project."""
    # Run MCP export synchronously for this endpoint
    normalized_spec = await load_normalized_spec(session, project.id)
    export_agent = ExportAgent()
    state: WorkflowState = {
        "project_id": str(project.id),
        "organization_id": str(project.organization_id),
        "workflow_run_id": str(uuid.uuid4()),
        "stages": ["export"],
        "target_languages": ["python", "node"],
        "normalized_spec": normalized_spec,
        "generated_files": [],
        "test_suite": [],
        "errors": [],
    }

    result = await export_agent.run(state, export_types=["mcp"])

    mcp_artifact = next(
        (a for a in result.get("exports", []) if a.get("type") == "mcp"),
        {"tools_generated": 0, "flagged_destructive": 0, "artifacts": []},
    )

    exp = Export(
        project_id=project.id,
        export_type=ExportType.MCP.value,
        status="completed",
    )
    session.add(exp)
    await session.commit()

    return MCPExportResponse(
        mcp_manifest_url=f"/api/v1/projects/{project.id}/exports/mcp/manifest.json",
        tools_generated=mcp_artifact.get("tools_generated", 0),
        flagged_destructive=mcp_artifact.get("flagged_destructive", 0),
    )


@router.get("/{id}/exports", response_model=list[dict])
async def list_exports(
    project: Project = Depends(require_project_permission(Permission.EXPORT_READ)),
    session: AsyncSession = Depends(get_db),
    limit: int = 20,
) -> list[dict]:
    """List export records for a project."""
    stmt = (
        select(Export)
        .where(Export.project_id == project.id)
        .order_by(Export.created_at.desc())
        .limit(limit)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    return [
        {
            "id": str(r.id),
            "export_type": r.export_type,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
