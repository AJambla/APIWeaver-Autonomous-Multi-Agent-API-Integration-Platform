"""`auth_configs`, `secrets_refs` — Database.md §3.12, §3.13."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import JSONB, Base, CreatedAtMixin, UUIDPrimaryKeyMixin, false_
from app.models.enums import AuthScheme, check_in


class AuthConfig(UUIDPrimaryKeyMixin, Base):
    """Target-API auth configuration. One per project (Database.md §3.12: UNIQUE)."""

    __tablename__ = "auth_configs"
    __table_args__ = (CheckConstraint(check_in("scheme", AuthScheme), name="scheme_valid"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    scheme: Mapped[str] = mapped_column(String(50), nullable=False)
    # Non-secret config only: header names, token URLs, scopes. Credentials go to Vault
    # (API.md §6.3 — `credentials` is never persisted here).
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB(), nullable=False)
    verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false_(), default=False
    )

    secrets_refs: Mapped[list[SecretRef]] = relationship(back_populates="auth_config")


class SecretRef(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A pointer into Vault — never a secret value (`Security.md §7`).

    Note the FK is `RESTRICT`, not `CASCADE`, unlike the rest of the project subtree.
    `Database.md §5` carves this out deliberately: deleting an auth config must first run
    an application-level Vault-deletion hook, because a DB cascade would orphan the
    secret in Vault with nothing left pointing at it. RESTRICT makes skipping that hook a
    hard error instead of a silent leak.

    TODO(Phase 2): implement the Vault-deletion hook in the secrets service alongside the
    hvac client, per Security.md §7.
    """

    __tablename__ = "secrets_refs"

    auth_config_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("auth_configs.id", ondelete="RESTRICT"), nullable=False
    )
    vault_path: Mapped[str] = mapped_column(String(1000), nullable=False)

    auth_config: Mapped[AuthConfig] = relationship(back_populates="secrets_refs")
