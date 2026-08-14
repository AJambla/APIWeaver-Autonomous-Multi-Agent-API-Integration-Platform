"""Document upload and normalized-spec read routes (Phase 2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.deps import get_current_principal, get_db, get_object_storage
from app.core.errors import UnprocessableEntityError
from app.models.enums import ActorType, HTTPMethod
from app.models.project import Project
from app.models.spec import APISpec, Endpoint
from app.rbac.enforce import require_project_permission
from app.rbac.policy import Permission, Principal
from app.schemas.document import EndpointResponse, SpecResponse, UploadResponse
from app.services import audit_service
from app.services.ingestion_service import ingest_document
from app.services.storage_service import ObjectStorage

router = APIRouter(prefix="/projects", tags=["documents"])


@router.post("/{id}/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
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
    return UploadResponse(document_id=document.id, api_spec_id=api_spec.id,
                          endpoints_discovered=len(normalized.endpoints))


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
