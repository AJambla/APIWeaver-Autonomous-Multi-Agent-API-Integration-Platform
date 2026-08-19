"""Organization API Key management routes (`API.md §1`, `Security.md §5`)."""

from __future__ import annotations

import datetime
import hashlib
import secrets
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.errors import NotFoundError
from app.models.enums import ActorType
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import APIKey
from app.rbac.enforce import require_org_permission
from app.rbac.policy import Permission, Principal
from app.schemas.api_key import (
    APIKeyCreateRequest,
    APIKeyCreateResponse,
    APIKeyListPage,
    APIKeyListResponse,
)
from app.services import audit_service

router = APIRouter(prefix="/org", tags=["api_keys"])


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _generate_key() -> tuple[str, str]:
    """Returns (plaintext_key, key_hash)."""
    raw = secrets.token_urlsafe(32)
    prefix = "apw_live_"
    full_key = prefix + raw
    return full_key, _hash_key(full_key)


@router.post(
    "/{org_id}/api-keys",
    response_model=APIKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_key(
    org_id: uuid.UUID,
    payload: APIKeyCreateRequest,
    principal: Principal = Depends(require_org_permission(Permission.ORG_MANAGE_API_KEYS)),
    session: AsyncSession = Depends(get_db),
) -> APIKeyCreateResponse:
    """Create a new API key for the organization."""
    # Verify org access (require_org_permission already checks membership)
    org = await session.get(Organization, org_id)
    if org is None:
        raise NotFoundError("Organization not found.")

    # If project_id provided, verify it belongs to this org
    if payload.project_id:
        project = await session.get(Project, payload.project_id)
        if project is None or project.organization_id != org.id:
            raise NotFoundError("Project not found in this organization.")

    plaintext_key, key_hash = _generate_key()
    prefix = "apw_live_"

    expires_at = None
    if payload.expires_in_days:
        now = datetime.datetime.now(datetime.UTC)
        expires_at = now + datetime.timedelta(days=payload.expires_in_days)

    api_key = APIKey(
        organization_id=org.id,
        project_id=payload.project_id,
        name=payload.name,
        key_prefix=prefix,
        key_hash=key_hash,
        created_by=principal.user_id,
        expires_at=expires_at,
    )
    session.add(api_key)
    await session.flush()

    await audit_service.record(
        session,
        action="api_key.created",
        actor_type=ActorType.USER,
        organization_id=org.id,
        actor_user_id=principal.user_id,
        resource_type="api_key",
        resource_id=str(api_key.id),
        metadata={
            "name": payload.name,
            "project_id": str(payload.project_id) if payload.project_id else None,
        },
    )

    return APIKeyCreateResponse(
        id=api_key.id,
        key=plaintext_key,  # Only returned once!
        prefix=prefix,
        name=api_key.name,
        project_id=api_key.project_id,
        expires_at=api_key.expires_at,
    )


@router.get("/{org_id}/api-keys", response_model=APIKeyListPage)
async def list_api_keys(
    org_id: uuid.UUID,
    principal: Principal = Depends(require_org_permission(Permission.ORG_MANAGE_API_KEYS)),
    session: AsyncSession = Depends(get_db),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> APIKeyListPage:
    """List API keys for the organization (prefix only, never full key)."""
    org = await session.get(Organization, org_id)
    if org is None:
        raise NotFoundError("Organization not found.")

    from app.schemas.common import PaginationMeta, decode_cursor, encode_cursor

    stmt = select(APIKey).where(APIKey.organization_id == org.id)

    if cursor and (position := decode_cursor(cursor)):
        try:
            last_created = datetime.datetime.fromisoformat(position["created_at"])
            last_id = uuid.UUID(position["id"])
            stmt = stmt.where(
                tuple_(APIKey.created_at, APIKey.id) < tuple_(last_created, last_id)
            )
        except (KeyError, TypeError, ValueError):
            pass

    stmt = stmt.order_by(APIKey.created_at.desc(), APIKey.id.desc()).limit(limit + 1)

    rows = list((await session.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    page_rows = rows[:limit]

    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor({"created_at": last.created_at.isoformat(), "id": str(last.id)})

    items = [
        APIKeyListResponse(
            id=row.id,
            prefix=row.key_prefix,
            name=row.name,
            project_id=row.project_id,
            created_at=row.created_at,
            expires_at=row.expires_at,
            revoked_at=row.revoked_at,
        )
        for row in page_rows
    ]

    return APIKeyListPage(
        data=items,
        pagination=PaginationMeta(next_cursor=next_cursor, has_more=has_more, limit=limit),
    )


@router.delete("/{org_id}/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    org_id: uuid.UUID,
    key_id: uuid.UUID,
    principal: Principal = Depends(require_org_permission(Permission.ORG_MANAGE_API_KEYS)),
    session: AsyncSession = Depends(get_db),
) -> None:
    """Revoke an API key."""
    org = await session.get(Organization, org_id)
    if org is None:
        raise NotFoundError("Organization not found.")

    api_key = await session.get(APIKey, key_id)
    if api_key is None or api_key.organization_id != org.id:
        raise NotFoundError("API key not found.")

    if api_key.revoked_at is not None:
        return  # Idempotent

    api_key.revoked_at = datetime.datetime.now(datetime.UTC)
    await session.flush()

    await audit_service.record(
        session,
        action="api_key.revoked",
        actor_type=ActorType.USER,
        organization_id=org.id,
        actor_user_id=principal.user_id,
        resource_type="api_key",
        resource_id=str(api_key.id),
        metadata={"name": api_key.name},
    )