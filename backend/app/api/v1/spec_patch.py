"""Spec Patch API route (`API.md §6.5`)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_principal, get_db
from app.core.errors import ConflictError, NotFoundError
from app.models.project import Project
from app.models.spec import APISpec, Endpoint, EndpointParameter
from app.rbac.enforce import require_project_permission
from app.rbac.policy import Permission, Principal
from app.schemas.spec_patch import EndpointPatchRequest, EndpointResponse
from app.services import audit_service

router = APIRouter(tags=["spec_patch"])


@router.patch(
    "/projects/{id}/spec/endpoints/{endpoint_id}",
    response_model=EndpointResponse,
    status_code=status.HTTP_200_OK,
)
async def patch_endpoint(
    id: uuid.UUID,
    endpoint_id: uuid.UUID,
    payload: EndpointPatchRequest,
    project: Project = Depends(require_project_permission(Permission.SPEC_UPDATE)),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> EndpointResponse:
    """Partially update an endpoint (method, path, schemas, parameters, etc.)."""
    # Verify project matches
    if project.id != id:
        raise NotFoundError("Project not found.")

    # Get the endpoint
    endpoint = await session.get(Endpoint, endpoint_id)
    if endpoint is None:
        raise NotFoundError("Endpoint not found.")

    # Verify endpoint belongs to project's latest spec
    latest_spec = await session.scalar(
        select(APISpec)
        .where(APISpec.project_id == project.id)
        .order_by(APISpec.created_at.desc())
        .limit(1)
    )
    if not latest_spec or endpoint.api_spec_id != latest_spec.id:
        raise NotFoundError("Endpoint not found in this project's current spec.")

    # Capture before state for audit
    before_state = {
        "method": endpoint.method,
        "path": endpoint.path,
        "summary": endpoint.summary,
        "request_schema": endpoint.request_schema,
        "response_schemas": endpoint.response_schemas,
        "deprecated": endpoint.deprecated,
        "is_destructive": endpoint.is_destructive,
        "confidence_score": float(endpoint.confidence_score) if endpoint.confidence_score else None,
    }

    # Apply partial update
    update_data = payload.model_dump(exclude_unset=True)
    parameters = update_data.pop("parameters", None)
    # These columns are NOT NULL: an explicit null means "leave as is", not "erase".
    for required in ("method", "path", "response_schemas", "deprecated", "is_destructive"):
        if required in update_data and update_data[required] is None:
            update_data.pop(required)

    new_method = update_data.get("method", endpoint.method)
    new_path = update_data.get("path", endpoint.path)
    if (new_method, new_path) != (endpoint.method, endpoint.path):
        # Each (method, path) is unique within a spec; the collision used to surface as
        # an IntegrityError and a 500.
        clash = await session.scalar(
            select(Endpoint.id).where(
                Endpoint.api_spec_id == endpoint.api_spec_id,
                Endpoint.method == new_method,
                Endpoint.path == new_path,
                Endpoint.id != endpoint.id,
            )
        )
        if clash is not None:
            raise ConflictError(f"This spec already has an endpoint {new_method} {new_path}.")

    for field, value in update_data.items():
        if hasattr(endpoint, field):
            setattr(endpoint, field, value)

    # Handle parameters replacement
    if parameters is not None:
        # Delete existing parameters
        await session.execute(
            delete(EndpointParameter).where(EndpointParameter.endpoint_id == endpoint.id)
        )
        # Insert new parameters
        for param in parameters:
            new_param = EndpointParameter(
                endpoint_id=endpoint.id,
                name=param["name"] if isinstance(param, dict) else param.name,
                location=param["location"] if isinstance(param, dict) else param.location,
                type=param["type"] if isinstance(param, dict) else param.type,
                required=param["required"] if isinstance(param, dict) else param.required,
            )
            session.add(new_param)

    await session.flush()
    await session.refresh(endpoint)

    # Capture after state
    after_state = {
        "method": endpoint.method,
        "path": endpoint.path,
        "summary": endpoint.summary,
        "request_schema": endpoint.request_schema,
        "response_schemas": endpoint.response_schemas,
        "deprecated": endpoint.deprecated,
        "is_destructive": endpoint.is_destructive,
        "confidence_score": float(endpoint.confidence_score) if endpoint.confidence_score else None,
    }

    await audit_service.record(
        session,
        action="endpoint.updated",
        # An API key is recorded as the system actor, not as a user with no id.
        **audit_service.actor(principal),
        organization_id=project.organization_id,
        resource_type="endpoint",
        resource_id=str(endpoint.id),
        metadata={"before": before_state, "after": after_state},
    )

    return EndpointResponse(
        id=str(endpoint.id),
        method=endpoint.method,
        path=endpoint.path,
        summary=endpoint.summary,
        request_schema=endpoint.request_schema,
        response_schemas=endpoint.response_schemas,
        deprecated=endpoint.deprecated,
        is_destructive=endpoint.is_destructive,
        confidence_score=float(endpoint.confidence_score) if endpoint.confidence_score else None,
    )