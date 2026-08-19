"""Document upload and normalized-spec read routes (Phase 2)."""

from __future__ import annotations

import uuid

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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.deps import get_current_principal, get_db, get_object_storage
from app.core.errors import UnprocessableEntityError
from app.models.enums import ActorType, HTTPMethod, WorkflowStatus
from app.models.project import Project
from app.models.spec import APISpec, Endpoint
from app.models.workflow import WorkflowRun
from app.rbac.enforce import require_project_permission
from app.rbac.policy import Permission, Principal
from app.schemas.document import EndpointResponse, SpecResponse, UploadResponse
from app.schemas.spec import EndpointPatchRequest, EndpointPatchResponse
from app.services import audit_service
from app.services.ingestion_service import ingest_document
from app.services.storage_service import ObjectStorage
from app.workflows.orchestrator import Orchestrator
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
    settings: Settings = Depends(get_settings),
) -> UploadResponse:
    if not file.filename:
        raise UnprocessableEntityError("A filename is required.")
    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise UnprocessableEntityError("The uploaded file exceeds the configured size limit.")
    if not content:
        raise UnprocessableEntityError("The uploaded file is empty.")

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
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    # Launch orchestrator in background
    initial_state: WorkflowState = {
        "project_id": str(project.id),
        "organization_id": str(project.organization_id),
        "workflow_run_id": str(run.id),
        "document_id": str(document.id),
        "raw_document_bytes": content,
        "document_filename": file.filename,
        "format_hint": format_hint,
        "stages": ["plan"],
        "normalized_spec": normalized.raw_normalized,
        "generated_files": [],
        "test_suite": [],
        "errors": [],
    }
    engine_session_factory = async_sessionmaker(
        bind=session.bind, class_=AsyncSession, expire_on_commit=False
    )
    orchestrator = Orchestrator(engine_session_factory)
    background_tasks.add_task(orchestrator.run, run.id, initial_state)

    return UploadResponse(
        document_id=document.id,
        status="processing",
        workflow_run_id=run.id,
        api_spec_id=api_spec.id,
        endpoints_discovered=len(normalized.endpoints),
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


@router.get("/{id}/endpoints", response_model=list[EndpointResponse])
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


@router.patch("/{id}/spec/endpoints/{endpoint_id}", response_model=EndpointPatchResponse)
async def patch_endpoint(
    endpoint_id: uuid.UUID,
    payload: EndpointPatchRequest,
    project: Project = Depends(require_project_permission(Permission.SPEC_UPDATE)),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    request: Request | None = None,
) -> EndpointPatchResponse:
    """Manual correction of a low-confidence endpoint."""
    current_spec = await session.scalar(
        select(APISpec)
        .where(APISpec.project_id == project.id)
        .order_by(APISpec.created_at.desc())
        .limit(1)
    )
    if current_spec is None:
        from app.core.errors import NotFoundError
        raise NotFoundError("No spec exists for this project.")

    endpoint = await session.get(Endpoint, endpoint_id)
    if endpoint is None or endpoint.api_spec_id != current_spec.id:
        from app.core.errors import NotFoundError
        raise NotFoundError("Endpoint not found in current spec.")

    updated_fields: list[str] = []
    before: dict[str, object] = {}
    after: dict[str, object] = {}

    if payload.path is not None and payload.path != endpoint.path:
        before["path"] = endpoint.path
        endpoint.path = payload.path
        after["path"] = payload.path
        updated_fields.append("path")

    if payload.method is not None and payload.method != endpoint.method:
        before["method"] = endpoint.method
        endpoint.method = payload.method
        after["method"] = payload.method
        updated_fields.append("method")

    if payload.summary is not None and payload.summary != endpoint.summary:
        before["summary"] = endpoint.summary
        endpoint.summary = payload.summary
        after["summary"] = payload.summary
        updated_fields.append("summary")

    if payload.request_schema is not None and payload.request_schema != endpoint.request_schema:
        before["request_schema"] = endpoint.request_schema
        endpoint.request_schema = payload.request_schema
        after["request_schema"] = payload.request_schema
        updated_fields.append("request_schema")

    if (
        payload.response_schemas is not None
        and payload.response_schemas != endpoint.response_schemas
    ):
        before["response_schemas"] = endpoint.response_schemas
        endpoint.response_schemas = payload.response_schemas
        after["response_schemas"] = payload.response_schemas
        updated_fields.append("response_schemas")

    import decimal

    new_confidence = (
        payload.confidence_score if payload.confidence_score is not None else decimal.Decimal("1.0")
    )
    if endpoint.confidence_score != new_confidence:
        before["confidence_score"] = (
            float(endpoint.confidence_score) if endpoint.confidence_score else None
        )
        endpoint.confidence_score = new_confidence
        after["confidence_score"] = float(new_confidence)
        updated_fields.append("confidence_score")

    if updated_fields:
        await session.flush()

        await audit_service.record(
            session,
            action="endpoint.patched",
            actor_type=ActorType.USER,
            organization_id=project.organization_id,
            actor_user_id=principal.user_id,
            resource_type="endpoint",
            resource_id=str(endpoint.id),
            ip_address=request.client.host if request and request.client else None,
            metadata={
                "updated_fields": updated_fields,
                "before": before,
                "after": after,
            },
        )

    return EndpointPatchResponse(
        endpoint_id=endpoint.id,
        updated_fields=updated_fields,
        confidence_score=float(endpoint.confidence_score) if endpoint.confidence_score else 1.0,
    )
