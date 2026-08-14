"""`sdk_packages`, `sdk_versions`, `exports`, `github_exports`, `mcp_tools`.

Database.md §3.23–§3.26.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import JSONB, Base, CreatedAtMixin, TZDateTime, UUIDPrimaryKeyMixin, false_
from app.models.enums import ExportType, TargetLanguage, check_in


class SDKPackage(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "sdk_packages"
    __table_args__ = (
        CheckConstraint(check_in("language", TargetLanguage), name="language_valid"),
        UniqueConstraint("project_id", "language", name="uniq_sdk_packages_project_language"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    language: Mapped[str] = mapped_column(String(20), nullable=False)
    package_name: Mapped[str] = mapped_column(String(255), nullable=False)

    versions: Mapped[list[SDKVersion]] = relationship(
        back_populates="sdk_package", cascade="all, delete-orphan"
    )


class SDKVersion(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "sdk_versions"
    __table_args__ = (
        UniqueConstraint("sdk_package_id", "semver", name="uniq_sdk_versions_package_semver"),
    )

    sdk_package_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sdk_packages.id", ondelete="CASCADE"), nullable=False
    )
    semver: Mapped[str] = mapped_column(String(50), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(1000), nullable=False)

    sdk_package: Mapped[SDKPackage] = relationship(back_populates="versions")


class Export(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "exports"
    __table_args__ = (
        CheckConstraint(check_in("export_type", ExportType), name="export_type_valid"),
        Index("idx_exports_project_id", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    export_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str | None] = mapped_column(String(20), nullable=True)

    github_export: Mapped[GitHubExport | None] = relationship(
        back_populates="export", cascade="all, delete-orphan", uselist=False
    )


class GitHubExport(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "github_exports"

    export_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exports.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    repo_full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    pushed_at: Mapped[datetime.datetime | None] = mapped_column(
        TZDateTime(), nullable=True
    )

    export: Mapped[Export] = relationship(back_populates="github_export")


class MCPTool(UUIDPrimaryKeyMixin, Base):
    """One generated MCP tool. `requires_confirmation` mirrors
    `endpoints.is_destructive` so a destructive operation cannot be invoked silently
    by an MCP host (Feature.md §19-24)."""

    __tablename__ = "mcp_tools"
    __table_args__ = (
        UniqueConstraint("project_id", "tool_name", name="uniq_mcp_tools_project_tool_name"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSONB(), nullable=False)
    requires_confirmation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false_(), default=False
    )
