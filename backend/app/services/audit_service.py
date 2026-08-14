"""Append-only audit log writer (`Security.md §17`).

This module exposes exactly one operation: `record`. There is intentionally no update or
delete path, which is the application-layer half of the immutability requirement. The
other half is a database GRANT withholding `UPDATE`/`DELETE` from the application role,
which belongs to infrastructure provisioning (Phase 6) since Alembic runs as the owner.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.enums import ActorType


async def record(
    session: AsyncSession,
    *,
    action: str,
    actor_type: ActorType = ActorType.USER,
    organization_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    """Append one audit entry.

    Added to the session but not committed — the caller's transaction owns the boundary,
    so the audit entry lands atomically with the action it describes. An action that rolls
    back leaves no audit claim that it happened.

    Callers must not pass secret values in `metadata`; log redaction (`Security.md §19`)
    covers log emission, not database columns.
    """
    entry = AuditLog(
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        actor_type=actor_type,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=ip_address,
        user_agent=user_agent,
        event_metadata=metadata,
    )
    session.add(entry)
    return entry
