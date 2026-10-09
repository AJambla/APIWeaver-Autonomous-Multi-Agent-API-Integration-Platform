"""Code generation API routes (`API.md §6.6`, `Feature.md §7-12`)."""

from __future__ import annotations

import datetime
import json
import uuid

import redis.asyncio as aioredis
from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.deps import get_current_principal, get_db, get_redis
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.models.codegen import CodeGenerationRun, GeneratedFile
from app.models.enums import WorkflowStatus
from app.models.project import Project
from app.models.versioning import ArtifactVersion
from app.models.workflow import WorkflowRun
from app.rbac.enforce import require_project_permission
from app.rbac.policy import Permission, Principal
from app.schemas.generate import FileContentResponse, FileResponse
from app.schemas.generate import GenerateRequest as GenerateRequestAlias
from app.schemas.generate import GenerateResponse as GenerateResponseAlias
from app.services import audit_service
from app.workflows.dispatch import dispatch_run
from app.workflows.state import WorkflowState

logger = get_logger(__name__)

router = APIRouter(prefix="/projects", tags=["generate"])


@router.post("/{id}/generate", response_model=GenerateResponseAlias, status_code=status.HTTP_202_ACCEPTED)
async def trigger_generate(
    payload: GenerateRequestAlias,
    background_tasks: BackgroundTasks,
    project: Project = Depends(require_project_permission(Permission.CODE_GENERATE)),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> GenerateResponseAlias:
    """Trigger code generation for a project."""
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

    # Find or create workflow run
    run = WorkflowRun(
        project_id=project.id,
        triggered_by=principal.user_id,
        status="queued",
    )
    session.add(run)
    await session.flush()

    await audit_service.record(
        session,
        **audit_service.actor(principal),
        action="code_generation.triggered",
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
        "generated_files": [],
        "test_suite": [],
        "errors": [],
    }

    await session.commit()
    await dispatch_run(
        run_id=run.id,
        state=initial_state,
        settings=settings,
        session=session,
        background_tasks=background_tasks,
        redis_client=redis_client,
    )

    return GenerateResponseAlias(workflow_run_id=run.id, status="queued")


@router.get("/{id}/files", response_model=list[FileResponse])
async def list_generated_files(
    limit: int = Query(default=200, ge=1, le=500),
    cursor: str | None = Query(default=None),
    project: Project = Depends(require_project_permission(Permission.CODE_READ)),
    session: AsyncSession = Depends(get_db),
) -> list[FileResponse]:
    active_ver = await session.scalar(
        select(ArtifactVersion)
        .where(
            ArtifactVersion.project_id == project.id,
            ArtifactVersion.artifact_type == "sdk",
            ArtifactVersion.is_active == True,  # noqa: E712
        )
        .order_by(ArtifactVersion.version_number.desc())
        .limit(1)
    )
    active_run_id = None
    if active_ver and active_ver.diff_ref:
        try:
            from app.services.storage_service import storage_service
            raw = await storage_service.download(active_ver.diff_ref)
            manifest = json.loads(raw.decode("utf-8"))
            if manifest.get("workflow_run_id"):
                active_run_id = uuid.UUID(manifest["workflow_run_id"])
        except Exception as exc:
            logger.warning("artifact_manifest_read_failed", diff_ref=active_ver.diff_ref, error=str(exc))

    stmt = (
        select(GeneratedFile, WorkflowRun.created_at.label("workflow_created_at"))
        .join(CodeGenerationRun, GeneratedFile.code_generation_run_id == CodeGenerationRun.id)
        .join(WorkflowRun, CodeGenerationRun.workflow_run_id == WorkflowRun.id)
        .where(WorkflowRun.project_id == project.id)
    )
    if active_run_id:
        stmt = stmt.where(WorkflowRun.id == active_run_id)
    stmt = stmt.order_by(WorkflowRun.created_at.desc(), GeneratedFile.id.asc()).limit(limit)

    rows = (await session.execute(stmt)).all()
    return [
        FileResponse(
            id=gf.id,
            project_id=project.id,
            file_path=gf.file_path,
            language=gf.language,
            file_type=gf.file_type,
            size_bytes=getattr(gf, "size_bytes", 0) or 0,
            created_at=created_at.isoformat() if created_at else None,
            code_generation_run_id=gf.code_generation_run_id,
        )
        for gf, created_at in rows
    ]


@router.get("/{id}/files/{file_id}/content", response_model=FileContentResponse)
async def get_file_content(
    file_id: uuid.UUID,
    project: Project = Depends(require_project_permission(Permission.CODE_READ)),
    session: AsyncSession = Depends(get_db),
) -> FileContentResponse:
    """Get the content of a generated file."""
    file_meta = (
        await session.execute(
            select(GeneratedFile)
            .join(CodeGenerationRun, GeneratedFile.code_generation_run_id == CodeGenerationRun.id)
            .join(WorkflowRun, CodeGenerationRun.workflow_run_id == WorkflowRun.id)
            .where(GeneratedFile.id == file_id, WorkflowRun.project_id == project.id)
        )
    ).scalar_one_or_none()
    if file_meta is None:
        # Also covers files owned by another project: 404 does not confirm they exist.
        raise NotFoundError("File not found.")

    from app.services.storage_service import storage_service
    content = await storage_service.download(file_meta.content_s3_key)
    text = content.decode("utf-8", errors="replace")

    return FileContentResponse(
        file_path=file_meta.file_path,
        content=text,
        language=file_meta.language,
        file_type=file_meta.file_type,
    )