"""GitHub OAuth models (Phase 4)."""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import JSONB, Base, CreatedAtMixin, TZDateTime, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User


class GitHubOAuthState(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """OAuth state for CSRF protection during GitHub authorization flow.

    Expires after 10 minutes to prevent reuse.
    """

    __tablename__ = "github_oauth_states"
    __table_args__ = (
        Index("idx_github_oauth_states_user_id", "user_id"),
        Index("idx_github_oauth_states_expires_at", "expires_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime.datetime] = mapped_column(TZDateTime(), nullable=False)


class GitHubConnection(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """User's GitHub connection (OAuth or GitHub App installation).

    Tokens are stored in Vault; this table holds only metadata and Vault paths.
    """

    __tablename__ = "github_connections"
    __table_args__ = (
        UniqueConstraint("user_id", "github_user_id", name="uniq_github_conn_user_github"),
        Index("idx_github_connections_user_id", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    github_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    github_username: Mapped[str] = mapped_column(String(255), nullable=False)
    access_token_vault_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    refresh_token_vault_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    scopes_granted: Mapped[dict[str, Any]] = mapped_column(
        JSONB(), default=lambda: {"user": [], "app": []}, nullable=False
    )
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(
        TZDateTime(), nullable=True
    )

    user: Mapped[User] = relationship()

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None