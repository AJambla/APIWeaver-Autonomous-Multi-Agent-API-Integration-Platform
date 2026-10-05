"""`audit_logs` — addendum §A.3, required by `Security.md §17`."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import INET, JSONB, Base, CreatedAtMixin, bigint_pk
from app.models.enums import ActorType, check_in


class AuditLog(CreatedAtMixin, Base):
    """Immutable record of a privileged action (`Security.md §17`).

    Append-only is enforced twice: `audit_service` exposes no mutation path, and
    alembic revision 0009 installs a row trigger on this table that refuses `UPDATE` and
    `DELETE` from any role while it is enabled, the owner included. The trigger exempts
    referential actions, so `ON DELETE CASCADE` from `organizations` and `ON DELETE SET
    NULL` from `users` keep working. Removing the trigger takes ownership of the table,
    which is why the application must not connect as the role that owns it.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint(check_in("actor_type", ActorType), name="actor_type_valid"),
        Index("idx_audit_logs_org_created", "organization_id", "created_at"),
        Index("idx_audit_logs_actor", "actor_user_id"),
    )

    id: Mapped[int] = bigint_pk()
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True
    )
    # Null for `agent` and `system` actors.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET(), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Named `event_metadata`, not `metadata` — the latter is reserved on the declarative
    # base (see ADDENDUM-Phase1.md §A.3).
    event_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB(), nullable=True)


class AuditAction:
    """Action identifiers for the privileged operations named in `Security.md §17`."""

    USER_REGISTERED = "user.registered"
    USER_LOGIN_SUCCEEDED = "user.login.succeeded"
    USER_LOGIN_FAILED = "user.login.failed"
    USER_LOGGED_OUT = "user.logged_out"
    TOKEN_REFRESHED = "token.refreshed"
    TOKEN_REUSE_DETECTED = "token.reuse_detected"
    ROLE_CHANGED = "role.changed"
    SECRET_ACCESSED = "secret.accessed"
    PROJECT_CREATED = "project.created"
    PROJECT_ARCHIVED = "project.archived"
    API_KEY_CREATED = "api_key.created"
    API_KEY_REVOKED = "api_key.revoked"
    EXPORT_TO_GITHUB = "export.github"
