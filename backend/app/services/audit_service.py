"""Append-only audit log writer (`Security.md §17`).

This module exposes exactly one operation: `record`. There is intentionally no update or
delete path, which is the application-layer half of the immutability requirement. The
other half is the row trigger installed by alembic revision 0009, which refuses
`UPDATE` and `DELETE` on `audit_logs` no matter which role issues them, so a bug or an
injected statement elsewhere in the application cannot rewrite history.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.enums import ActorType


def actor(principal: Any) -> dict[str, Any]:
    """`actor_type` and `actor_user_id` for an authenticated principal.

    An API key acts as the organization (no user), so it is recorded as a system actor;
    a JWT principal is the user behind it. Every route should pass `**actor(principal)`
    so no audit row is left without an actor.
    """
    is_key = bool(getattr(principal, "is_api_key", False))
    return {
        "actor_type": ActorType.SYSTEM if is_key else ActorType.USER,
        "actor_user_id": getattr(principal, "user_id", None),
    }


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
