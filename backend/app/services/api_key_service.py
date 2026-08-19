"""API key management service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_api_key
from app.models.user import APIKey


async def create_api_key(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    name: str,
    created_by: uuid.UUID | None,
    project_id: uuid.UUID | None = None,
    expires_at: datetime | None = None,
    live: bool = True,
) -> tuple[APIKey, str]:
    """Create a new API key.

    Returns tuple of (APIKey model, plaintext key) - the plaintext is shown only once.
    """
    generated = generate_api_key(live=live)

    api_key = APIKey(
        organization_id=organization_id,
        name=name,
        key_prefix=generated.prefix,
        key_hash=generated.key_hash,
        created_by=created_by,
        project_id=project_id,
        expires_at=expires_at,
    )
    session.add(api_key)
    await session.flush()

    return api_key, generated.plaintext


async def list_api_keys(
    session: AsyncSession,
    organization_id: uuid.UUID,
) -> list[APIKey]:
    """List all API keys for an organization."""
    result = await session.execute(
        select(APIKey)
        .where(APIKey.organization_id == organization_id)
        .order_by(APIKey.created_at.desc())
    )
    return list(result.scalars())


async def revoke_api_key(
    session: AsyncSession,
    *,
    api_key_id: uuid.UUID,
    organization_id: uuid.UUID,
) -> APIKey | None:
    """Revoke an API key by setting revoked_at timestamp."""
    api_key = await session.get(APIKey, api_key_id)
    if api_key is None or api_key.organization_id != organization_id:
        return None

    if api_key.revoked_at is not None:
        return api_key

    api_key.revoked_at = datetime.now(UTC)
    await session.flush()
    return api_key
