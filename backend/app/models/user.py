"""`users` (Database.md §3.2) plus `refresh_tokens` and `api_keys` (addendum §A.1, §A.2)."""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, TZDateTime, UUIDPrimaryKeyMixin, false_

if TYPE_CHECKING:
    from app.models.organization import OrganizationMember
    from app.models.project import ProjectMember


class User(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    # Nullable for SSO-only accounts (Database.md §3.2, Security.md §1).
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mfa_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false_(), default=False
    )

    organization_memberships: Mapped[list[OrganizationMember]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    project_memberships: Mapped[list[ProjectMember]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One row per issued refresh token (addendum §A.1).

    `Security.md §1` requires single-use rotation with family-level revocation on reuse.
    `family_id` groups every token descended from one login: replaying a spent token
    revokes the whole family, which is the compromise signal.

    Only the SHA-256 of the token is stored, so this row is a lookup handle rather than
    a credential at rest.
    """

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("idx_refresh_tokens_user_id", "user_id"),
        Index("idx_refresh_tokens_family_id", "family_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    family_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime.datetime] = mapped_column(TZDateTime(), nullable=False)
    # Non-null means already redeemed — a second redemption is a replay.
    used_at: Mapped[datetime.datetime | None] = mapped_column(
        TZDateTime(), nullable=True
    )
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(
        TZDateTime(), nullable=True
    )

    user: Mapped[User] = relationship(back_populates="refresh_tokens")

    @property
    def is_active(self) -> bool:
        now = datetime.datetime.now(datetime.UTC)
        return self.revoked_at is None and self.used_at is None and self.expires_at > now


class APIKey(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Programmatic credential, scoped per organization (addendum §A.2).

    Per `Security.md §5` only `key_prefix` is retrievable for UI identification; the
    key itself exists in plaintext exactly once, in the creation response.
    """

    __tablename__ = "api_keys"
    __table_args__ = (
        # Guard against a key that is neither live nor test (Security.md §5 format).
        CheckConstraint("key_prefix IN ('apw_live_', 'apw_test_')", name="key_prefix_valid"),
        Index("idx_api_keys_org_id", "organization_id"),
        Index("idx_api_keys_prefix", "key_prefix"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # Optional narrowing of an org-scoped key to a single project (Security.md §5).
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime.datetime | None] = mapped_column(
        TZDateTime(), nullable=True
    )
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(
        TZDateTime(), nullable=True
    )

    @property
    def is_active(self) -> bool:
        if self.revoked_at is not None:
            return False
        if self.expires_at is None:
            return True
        return self.expires_at > datetime.datetime.now(datetime.UTC)
