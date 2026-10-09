"""Document upload and normalized-spec read routes (Phase 2)."""

from __future__ import annotations

import redis.asyncio as aioredis
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Query,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.constants import DEFAULT_TARGET_LANGUAGES
from app.core.deps import client_ip, get_current_principal, get_db, get_object_storage, get_redis
from app.core.errors import UnprocessableEntityError
from app.models.enums import ActorType, HTTPMethod, WorkflowStatus
from app.models.project import Project
from app.models.spec import APISpec, Endpoint
from app.models.workflow import WorkflowRun
from app.rbac.enforce import require_project_permission
from app.rbac.policy import Permission, Principal
from app.schemas.document import (
    EndpointResponse,
    FetchSpecRequest,
    FetchSpecResponse,
    SpecResponse,
    UploadResponse,
)
from app.services import audit_service
from app.services.ingestion_service import ingest_document
from app.services.remote_fetch import fetch_text
from app.services.storage_service import ObjectStorage
from app.workflows.dispatch import dispatch_run
from app.workflows.state import WorkflowState

router = APIRouter(prefix="/projects", tags=["documents"])


@router.post("/{id}/upload", response_model=UploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    format_hint: str | None = Form(default=None),
    project: Project = Depends(require_project_permission(Permission.DOCUMENT_UPLOAD)),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_object_storage),
    redis_client: aioredis.Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> UploadResponse:
    if not file.filename:
        raise UnprocessableEntityError("A filename is required.")
    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise UnprocessableEntityError("The uploaded file exceeds the configured size limit.")
    if not content:
        raise UnprocessableEntityError("The uploaded file is empty.")

    # A refusal raised here propagates as 422, like the input checks above: `status: 202`
    # means an async workflow started (`API.md §5`), and there is nothing to process if no
    # document was accepted. Deciding that freeform input is *not* a refusal belongs to
    # `ingest_document`, which normalizes defensively and returns the document alone.
    document, api_spec, normalized = await ingest_document(
        session,
        storage,
        project_id=project.id,
        uploaded_by=principal.user_id,
        filename=file.filename,
        content=content,
        content_type=file.content_type,
        format_hint=format_hint,
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
        stale.error_details = {"reason": "superseded_by_new_upload"}

    # Create associated workflow run for parsing & planning pipeline
    run = WorkflowRun(
        project_id=project.id,
        triggered_by=principal.user_id,
        status=WorkflowStatus.RUNNING,
    )
    session.add(run)
    await session.flush()

    await audit_service.record(
        session,
        action="document.uploaded",
        actor_type=ActorType.SYSTEM if principal.is_api_key else ActorType.USER,
        organization_id=project.organization_id,
        actor_user_id=principal.user_id,
        resource_type="document",
        resource_id=str(document.id),
        ip_address=client_ip(request, settings),
        user_agent=request.headers.get("user-agent"),
    )

    normalized_spec_dict = None
    if normalized:
        endpoints_data = [
            {
                "method": ep.method,
                "path": ep.path,
                "summary": ep.summary,
                "operation_id": ep.operation_id,
                "operationId": ep.operation_id,
                "parameters": ep.parameters,
                "request_schema": ep.request_schema,
                "response_schemas": ep.response_schemas,
            }
            for ep in normalized.endpoints
        ]
        raw_dict = dict(normalized.raw_normalized or {})
        raw_dict["title"] = normalized.title or raw_dict.get("title", "API Specification")
        raw_dict["base_url"] = normalized.base_url or raw_dict.get("base_url", "")
        raw_dict["format"] = normalized.format
        raw_dict["endpoints"] = endpoints_data
        normalized_spec_dict = raw_dict

    # Launch orchestrator in background
    initial_state: WorkflowState = {
        "project_id": str(project.id),
        "organization_id": str(project.organization_id),
        "workflow_run_id": str(run.id),
        "document_id": str(document.id),
        "raw_document_bytes": content,
        # The worker reloads the bytes from object storage (they do not travel in the
        # broker message).
        "document_s3_key": document.s3_key,
        "document_filename": file.filename,
        "format_hint": format_hint,
        "stages": ["plan"],
        "target_languages": list(DEFAULT_TARGET_LANGUAGES),
        "normalized_spec": normalized_spec_dict,
        "spec_persisted": api_spec is not None,
        "endpoints_discovered": len(normalized.endpoints) if normalized else 0,
        "generated_files": [],
        "test_suite": [],
        "errors": [],
    }

    # Commit before dispatching background worker so concurrent sessions see all persisted rows
    await session.commit()

    await dispatch_run(
        run_id=run.id,
        state=initial_state,
        settings=settings,
        session=session,
        background_tasks=background_tasks,
        redis_client=redis_client,
    )

    return UploadResponse(
        document_id=document.id,
        status="processing",
        workflow_run_id=run.id,
        api_spec_id=api_spec.id if api_spec else None,
        endpoints_discovered=len(normalized.endpoints) if normalized else 0,
    )


@router.post("/{id}/fetch-spec", response_model=FetchSpecResponse)
async def fetch_spec_from_url(
    payload: FetchSpecRequest,
    project: Project = Depends(require_project_permission(Permission.DOCUMENT_UPLOAD)),
    settings: Settings = Depends(get_settings),
) -> FetchSpecResponse:
    """Fetch a specification by URL for review before upload.

    Server-side because the SPA's CSP only allows its own origin; SSRF-guarded on every
    redirect hop and capped at the upload size limit. Nothing is stored.
    """
    content, content_type = await fetch_text(
        payload.url,
        max_bytes=settings.max_upload_bytes,
        allow_private=settings.spec_fetch_allow_private_targets,
    )
    return FetchSpecResponse(
        content=content, content_type=content_type, size_bytes=len(content.encode("utf-8"))
    )


@router.get("/{id}/spec", response_model=SpecResponse)
async def get_spec(
    project: Project = Depends(require_project_permission(Permission.SPEC_READ)),
    session: AsyncSession = Depends(get_db),
) -> SpecResponse:
    spec = await session.scalar(
        select(APISpec)
        .where(APISpec.project_id == project.id)
        .order_by(APISpec.created_at.desc())
        .limit(1)
    )
    if spec is None:
        raise UnprocessableEntityError("No normalized API specification exists for this project.")
    return SpecResponse.model_validate(spec)


@router.get(
    "/{id}/endpoints",
    response_model=list[EndpointResponse],
    response_model_exclude_none=True,
)
async def list_endpoints(
    project: Project = Depends(require_project_permission(Permission.SPEC_READ)),
    session: AsyncSession = Depends(get_db),
    method: HTTPMethod | None = Query(default=None),
    deprecated: bool | None = Query(default=None),
    confidence_min: float | None = Query(default=None, ge=0, le=1),
) -> list[EndpointResponse]:
    stmt = select(Endpoint).join(APISpec).where(APISpec.project_id == project.id)
    if method is not None:
        stmt = stmt.where(Endpoint.method == method)
    if deprecated is not None:
        stmt = stmt.where(Endpoint.deprecated == deprecated)
    if confidence_min is not None:
        stmt = stmt.where(Endpoint.confidence_score >= confidence_min)
    rows = list((await session.execute(stmt.order_by(Endpoint.path, Endpoint.method))).scalars())
    return [EndpointResponse.model_validate(row) for row in rows]
