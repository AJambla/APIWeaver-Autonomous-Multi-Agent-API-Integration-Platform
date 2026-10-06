"""Code generation API routes (`API.md §6.6`, `Feature.md §7-12`)."""

from __future__ import annotations

import uuid

import redis.asyncio as aioredis
from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_principal, get_db, get_redis
from app.core.errors import NotFoundError
from app.models.codegen import CodeGenerationRun, GeneratedFile
from app.models.enums import ActorType, WorkflowStatus
from app.models.project import Project
from app.models.workflow import WorkflowRun
from app.rbac.enforce import require_project_permission
from app.rbac.policy import Permission, Principal
from app.schemas.generate import FileContentResponse, FileResponse
from app.schemas.generate import GenerateRequest as GenerateRequestAlias
from app.schemas.generate import GenerateResponse as GenerateResponseAlias
from app.services import audit_service
from app.services.event_publisher import EventPublisher
from app.workflows.langgraph_pipeline import LangGraphOrchestrator
from app.workflows.state import WorkflowState

router = APIRouter(prefix="/projects", tags=["generate"])


@router.post("/{id}/generate", response_model=GenerateResponseAlias, status_code=status.HTTP_202_ACCEPTED)
async def trigger_generate(
    payload: GenerateRequestAlias,
    background_tasks: BackgroundTasks,
    project: Project = Depends(require_project_permission(Permission.CODE_GENERATE)),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
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
        stale.error_details = {"reason": "superseded_by_new_generate"}

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
    orchestrator = LangGraphOrchestrator(
        session_factory=engine_session_factory,
        event_publisher=EventPublisher(redis_client),
    )
    background_tasks.add_task(orchestrator.run, run.id, initial_state)

    return GenerateResponseAlias(workflow_run_id=run.id, status="queued")


@router.get("/{id}/files", response_model=list[FileResponse])
async def list_generated_files(
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
    project: Project = Depends(require_project_permission(Permission.CODE_READ)),
    session: AsyncSession = Depends(get_db),
) -> list[FileResponse]:
    """List generated files for a project."""
    stmt = (
        select(GeneratedFile)
        .join(CodeGenerationRun, GeneratedFile.code_generation_run_id == CodeGenerationRun.id)
        .join(WorkflowRun, CodeGenerationRun.workflow_run_id == WorkflowRun.id)
        .where(WorkflowRun.project_id == project.id)
        .order_by(GeneratedFile.id)
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
        )
        for row in rows
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