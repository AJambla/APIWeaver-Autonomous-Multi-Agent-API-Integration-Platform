"""Code generation API routes (`API.md §6.6`, `Feature.md §7-12`)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.errors import NotFoundError
from app.models.codegen import CodeGenerationRun, GeneratedFile
from app.models.enums import ActorType
from app.models.project import Project
from app.models.workflow import WorkflowRun
from app.rbac.enforce import load_project_for_principal, require_project_permission
from app.rbac.policy import Permission, Principal
from app.schemas.generate import FileContentResponse, FileResponse
from app.schemas.generate import GenerateRequest as GenerateRequestAlias
from app.schemas.generate import GenerateResponse as GenerateResponseAlias
from app.services import audit_service
from app.workflows.orchestrator import Orchestrator
from app.workflows.state import WorkflowState

router = APIRouter(prefix="/projects", tags=["generate"])


@router.post("/{id}/generate", response_model=GenerateResponseAlias, status_code=status.HTTP_202_ACCEPTED)
async def trigger_generate(
    project_id: uuid.UUID,
    payload: GenerateRequestAlias,
    background_tasks: BackgroundTasks,
    principal: Principal = Depends(require_project_permission(Permission.CODE_GENERATE)),
    session: AsyncSession = Depends(get_db),
) -> GenerateResponseAlias:
    """Trigger code generation for a project."""
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFoundError("Project not found.")

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
        action="code_generation.triggered",
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
        "generated_files": [],
        "test_suite": [],
        "errors": [],
    }

    engine_session_factory = __import__("sqlalchemy.ext.asyncio", fromlist=["async_sessionmaker"]).async_sessionmaker(
        bind=session.bind, class_=AsyncSession, expire_on_commit=False
    )
    orchestrator = Orchestrator(engine_session_factory)
    background_tasks.add_task(orchestrator.run, run.id, initial_state)

    return GenerateResponseAlias(workflow_run_id=run.id, status="queued")


@router.get("/{id}/files", response_model=list[FileResponse])
async def list_generated_files(
    project_id: uuid.UUID,
    principal: Principal = Depends(require_project_permission(Permission.CODE_READ)),
    session: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> list[FileResponse]:
    """List generated files for a project."""
    project = await load_project_for_principal(session, principal, project_id)

    stmt = (
        select(GeneratedFile)
        .join(CodeGenerationRun, GeneratedFile.code_generation_run_id == CodeGenerationRun.id)
        .where(CodeGenerationRun.project_id == project.id)
        .order_by(GeneratedFile.created_at.desc())
        .limit(limit)
    )

    rows = list((await session.execute(stmt)).scalars())
    return [
        FileResponse(
            id=row.id,
            project_id=project.id,
            file_path=row.file_path,
            language=row.language,
            file_type=row.file_type,
            size_bytes=0,
            created_at=row.created_at.isoformat() if row.created_at else None,
        )
        for row in rows
    ]


@router.get("/{id}/files/{file_id}/content", response_model=FileContentResponse)
async def get_file_content(
    project_id: uuid.UUID,
    file_id: uuid.UUID,
    principal: Principal = Depends(require_project_permission(Permission.CODE_READ)),
    session: AsyncSession = Depends(get_db),
) -> FileContentResponse:
    """Get the content of a generated file."""
    await load_project_for_principal(session, principal, project_id)

    file_meta = await session.get(GeneratedFile, file_id)
    if file_meta is None:
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