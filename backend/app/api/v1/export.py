"""Export API routes (`API.md §6.8`, `Feature.md §15-24`)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.deps import get_db
from app.core.errors import NotFoundError
from app.models.enums import ActorType, ExportType
from app.models.export import Export
from app.models.project import Project
from app.rbac.enforce import load_project_for_principal, require_project_permission
from app.rbac.policy import Permission, Principal
from app.schemas.export import ExportRequest, ExportResponse, MCPExportResponse
from app.services import audit_service
from app.workflows.agents.export_agent import ExportAgent
from app.workflows.orchestrator import Orchestrator
from app.workflows.state import WorkflowState

router = APIRouter(prefix="/projects", tags=["export"])


@router.post("/{id}/export", response_model=ExportResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_export(
    project_id: uuid.UUID,
    payload: ExportRequest,
    background_tasks: BackgroundTasks,
    principal: Principal = Depends(require_project_permission(Permission.EXPORT_CREATE)),
    session: AsyncSession = Depends(get_db),
) -> ExportResponse:
    """Trigger artifact exports for a project."""
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFoundError("Project not found.")

    # Create export record
    export_types = payload.export_types or [e.value for e in ExportType]
    artifacts_meta = []

    for export_type in export_types:
        exp = Export(
            project_id=project.id,
            export_type=export_type,
            status="queued",
        )
        session.add(exp)
        await session.flush()
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

    # Run export in background
    engine_session_factory = async_sessionmaker(
        bind=session.bind, class_=AsyncSession, expire_on_commit=False
    )
    orchestrator = Orchestrator(engine_session_factory)

    initial_state: WorkflowState = {
        "project_id": str(project.id),
        "organization_id": str(project.organization_id),
        "workflow_run_id": str(uuid.uuid4()),
        "stages": ["export"],
        "target_languages": ["python", "node"],
        "generated_files": [],
        "test_suite": [],
        "errors": [],
    }

    background_tasks.add_task(orchestrator.run, uuid.UUID(initial_state["workflow_run_id"]), initial_state)

    return ExportResponse(export_id=uuid.uuid4(), artifacts=artifacts_meta)


@router.post("/{id}/export/mcp", response_model=MCPExportResponse)
async def export_mcp(
    project_id: uuid.UUID,
    principal: Principal = Depends(require_project_permission(Permission.EXPORT_CREATE)),
    session: AsyncSession = Depends(get_db),
) -> MCPExportResponse:
    """Export MCP tools for a project."""
    project = await load_project_for_principal(session, principal, project_id)

    # Run MCP export synchronously for this endpoint
    export_agent = ExportAgent()
    state: WorkflowState = {
        "project_id": str(project.id),
        "organization_id": str(project.organization_id),
        "workflow_run_id": str(uuid.uuid4()),
        "stages": ["export"],
        "target_languages": ["python", "node"],
        "generated_files": [],
        "test_suite": [],
        "errors": [],
    }

    result = await export_agent.run(state, export_types=["mcp"])

    mcp_artifact = next(
        (a for a in result.get("exports", []) if a.get("type") == "mcp"),
        {"tools_generated": 0, "flagged_destructive": 0, "artifacts": []},
    )

    return MCPExportResponse(
        mcp_manifest_url=f"/api/v1/projects/{project_id}/exports/mcp/manifest.json",
        tools_generated=mcp_artifact.get("tools_generated", 0),
        flagged_destructive=mcp_artifact.get("flagged_destructive", 0),
    )