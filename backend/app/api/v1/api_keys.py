"""API key management routes (`API.md §1`)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from fastapi import Request as FastAPIRequest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.errors import NotFoundError, UnprocessableEntityError
from app.models.enums import ActorType
from app.models.project import Project
from app.rbac.enforce import require_org_permission
from app.rbac.policy import Permission, Principal
from app.schemas.api_key import (
    APIKeyListItem,
    APIKeyListResponse,
    APIKeyResponse,
    CreateAPIKeyRequest,
)
from app.services import audit_service
from app.services.api_key_service import create_api_key, list_api_keys, revoke_api_key

router = APIRouter(prefix="/org", tags=["api-keys"])


@router.post(
    "/{org_id}/api-keys",
    response_model=APIKeyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_org_api_key(
    org_id: uuid.UUID,
    payload: CreateAPIKeyRequest,
    principal: Principal = Depends(require_org_permission(Permission.ORG_MANAGE_API_KEYS)),
    session: AsyncSession = Depends(get_db),
    request: FastAPIRequest | None = None,
) -> APIKeyResponse:
    """Create new API key for organization."""
    if payload.project_id is not None:
        project = await session.get(Project, payload.project_id)
        if project is None or project.organization_id != org_id:
            raise UnprocessableEntityError("Project must belong to the same organization.")

    api_key, plaintext = await create_api_key(
        session,
        organization_id=org_id,
        name=payload.name,
        created_by=principal.user_id,
        project_id=payload.project_id,
        expires_at=payload.expires_at,
        live=payload.live,
    )

    await audit_service.record(
        session,
        action="api_key.created",
        actor_type=ActorType.USER,
        organization_id=org_id,
        actor_user_id=principal.user_id,
        resource_type="api_key",
        resource_id=str(api_key.id),
        ip_address=request.client.host if request and request.client else None,
        metadata={
            "name": payload.name,
            "key_prefix": api_key.key_prefix,
            "project_id": str(payload.project_id) if payload.project_id else None,
        },
    )

    return APIKeyResponse(
        id=api_key.id,
        name=api_key.name,
        key=plaintext,
        key_prefix=api_key.key_prefix,
        project_id=api_key.project_id,
        created_at=api_key.created_at,
        expires_at=api_key.expires_at,
    )


@router.get("/{org_id}/api-keys", response_model=APIKeyListResponse)
async def list_org_api_keys(
    org_id: uuid.UUID,
    principal: Principal = Depends(require_org_permission(Permission.ORG_MANAGE_API_KEYS)),
    session: AsyncSession = Depends(get_db),
) -> APIKeyListResponse:
    """List API keys for organization."""
    keys = await list_api_keys(session, org_id)

    return APIKeyListResponse(
        data=[
            APIKeyListItem(
                id=key.id,
                name=key.name,
                key_prefix=key.key_prefix,
                project_id=key.project_id,
                created_at=key.created_at,
                expires_at=key.expires_at,
                is_active=key.is_active,
            )
            for key in keys
        ]
    )


@router.delete("/{org_id}/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_org_api_key(
    org_id: uuid.UUID,
    key_id: uuid.UUID,
    principal: Principal = Depends(require_org_permission(Permission.ORG_MANAGE_API_KEYS)),
    session: AsyncSession = Depends(get_db),
    request: FastAPIRequest | None = None,
) -> None:
    """Revoke an API key."""
    api_key = await revoke_api_key(
        session,
        api_key_id=key_id,
        organization_id=org_id,
    )

    if api_key is None:
        raise NotFoundError("API key not found.")

    await audit_service.record(
        session,
        action="api_key.revoked",
        actor_type=ActorType.USER,
        organization_id=org_id,
        actor_user_id=principal.user_id,
        resource_type="api_key",
        resource_id=str(key_id),
        ip_address=request.client.host if request and request.client else None,
    )
