"""Export API routes (`API.md §6.8`, `Feature.md §15-24`)."""

from __future__ import annotations

import uuid

import redis.asyncio as aioredis
from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.constants import DEFAULT_TARGET_LANGUAGES
from app.core.deps import get_current_principal, get_db, get_redis
from app.core.errors import APIError, NotFoundError
from app.models.enums import ExportType, WorkflowStatus
from app.models.export import Export
from app.models.project import Project
from app.models.workflow import WorkflowRun
from app.rbac.enforce import require_project_permission
from app.rbac.policy import Permission, Principal
from app.schemas.export import ExportRequest, ExportResponse, MCPExportResponse
from app.services import audit_service
from app.services.workflow_input_service import (
    load_generated_files,
    load_latest_test_results,
    load_normalized_spec,
)
from app.workflows.agents.export_agent import ExportAgent
from app.workflows.dispatch import dispatch_run
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
    settings: Settings = Depends(get_settings),
) -> ExportResponse:
    """Trigger artifact exports for a project."""
    # Create export record
    export_types = [str(t) for t in payload.export_types]
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
        **audit_service.actor(principal),
        action="export.triggered",
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
        "target_languages": payload.target_languages or list(DEFAULT_TARGET_LANGUAGES),
        "normalized_spec": normalized_spec,
        "generated_files": generated_files,
        "test_suite": test_suite,
        "test_run_summary": test_run_summary,
        "export_types": export_types,
        "github_repo_name": payload.github_repo_name,
        "github_org": payload.github_org,
        "github_private": payload.github_private,
        "github_branch": payload.github_branch,
        "github_commit_message": payload.github_commit_message,
        "docker_image_name": payload.docker_image_name,
        "errors": [],
    }

    await dispatch_run(
        run_id=run.id,
        state=initial_state,
        settings=settings,
        session=session,
        background_tasks=background_tasks,
        redis_client=redis_client,
        post_run={
            "kind": "export",
            "export_ids": {k: str(v) for k, v in export_ids.items()},
        },
    )

    return ExportResponse(export_id=run.id, artifacts=artifacts_meta)


@router.post("/{id}/export/mcp", response_model=MCPExportResponse)
async def export_mcp(
    project: Project = Depends(require_project_permission(Permission.EXPORT_CREATE)),
    session: AsyncSession = Depends(get_db),
) -> MCPExportResponse:
    """Export MCP tools for a project."""
    # Run MCP export synchronously for this endpoint
    normalized_spec = await load_normalized_spec(session, project.id)
    if not normalized_spec or not normalized_spec.get("endpoints"):
        raise NotFoundError("Project has no normalized API specification to export MCP tools from.")

    export_agent = ExportAgent()
    state: WorkflowState = {
        "project_id": str(project.id),
        "organization_id": str(project.organization_id),
        "workflow_run_id": str(uuid.uuid4()),
        "stages": ["export"],
        "target_languages": list(DEFAULT_TARGET_LANGUAGES),
        "normalized_spec": normalized_spec,
        "generated_files": [],
        "test_suite": [],
        "errors": [],
    }

    result = await export_agent.run(state, export_types=["mcp"])

    mcp_artifact = next(
        (a for a in result.get("exports", []) if a.get("type") == "mcp"),
        None,
    )

    mcp_failed = (
        mcp_artifact is None
        or mcp_artifact.get("status") == "failed"
        or result.get("status") == "failed"
    )
    manifest_s3_key = f"exports/{project.id}/mcp/manifest.json"
    exp = Export(
        project_id=project.id,
        export_type=ExportType.MCP.value,
        status="failed" if mcp_failed else "completed",
        s3_key=manifest_s3_key if not mcp_failed else None,
    )
    session.add(exp)
    await session.commit()

    if mcp_failed:
        error_msg = (mcp_artifact.get("error") if mcp_artifact else None) or "MCP export packaging failed."
        raise APIError(error_msg)

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
            "download_url": f"/api/v1/projects/{project.id}/exports/{r.id}/download" if r.status == "completed" else None,
        }
        for r in rows
    ]


@router.get("/{id}/exports/{export_id}/download")
async def download_export(
    export_id: uuid.UUID,
    project: Project = Depends(require_project_permission(Permission.EXPORT_READ)),
    session: AsyncSession = Depends(get_db),
):
    """Download the generated export package bundle."""
    from fastapi import Response

    from app.core.errors import NotFoundError
    from app.services.storage_service import storage_service

    export = await session.get(Export, export_id)
    if export is None or export.project_id != project.id:
        raise NotFoundError("Export record not found.")

    candidate_keys = []
    if export.s3_key:
        candidate_keys.append(export.s3_key)
    candidate_keys.extend([
        f"exports/{project.id}/{export.export_type}/python/sdk-python.zip",
        f"exports/{project.id}/{export.export_type}/node/sdk-node.zip",
        f"exports/{project.id}/{export.export_type}/python/package.json",
        f"exports/{project.id}/{export.export_type}/node/package.json",
        f"exports/{project.id}/{export.export_type}/python/client.py",
        f"exports/{project.id}/{export.export_type}/node/client.ts",
        f"exports/{project.id}/{export.export_type}/Dockerfile",
        f"exports/{project.id}/{export.export_type}/package.json",
        f"exports/{project.id}/{export.export_type}/manifest.json",
        f"exports/{project.id}/mcp/manifest.json",
        f"exports/{project.id}/mcp/mcp_manifest.json",
    ])

    content: bytes | None = None
    matched_key: str | None = None
    for key in candidate_keys:
        try:
            content = await storage_service.download(key)
            if content:
                matched_key = key
                break
        except Exception:
            continue

    if not content:
        raise NotFoundError(f"No downloadable artifact found for export {export_id}.")

    filename = matched_key.split("/")[-1] if matched_key else f"export-{export.export_type}.zip"
    media_type = "application/zip" if filename.endswith(".zip") else ("application/json" if filename.endswith(".json") else "application/octet-stream")
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{id}/exports/mcp/manifest.json")
async def download_mcp_manifest(
    id: uuid.UUID,
    project: Project = Depends(require_project_permission(Permission.EXPORT_READ)),
    session: AsyncSession = Depends(get_db),
):
    """Download the MCP manifest JSON for a project."""
    from fastapi import Response

    from app.core.errors import NotFoundError
    from app.services.storage_service import storage_service

    manifest_key = f"exports/{project.id}/mcp/manifest.json"
    try:
        content = await storage_service.download(manifest_key)
    except Exception:
        content = None

    if not content:
        raise NotFoundError("MCP manifest not found. Please generate an MCP export first.")

    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=manifest.json"},
    )
