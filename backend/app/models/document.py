"""`documents`, `document_versions` — Database.md §3.6, §3.7."""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import JSONB, Base, CreatedAtMixin, TZDateTime, UUIDPrimaryKeyMixin, utcnow
from app.models.enums import DocumentFormat, check_in

if TYPE_CHECKING:
    from app.models.project import Project


class Document(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(check_in("format", DocumentFormat), name="format_valid"),
        Index("idx_documents_project_id", "project_id"),
        # Prevents re-processing an identical upload within a project (Database.md §5).
        UniqueConstraint("project_id", "checksum_sha256", name="uniq_documents_checksum"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    format: Mapped[str] = mapped_column(String(50), nullable=False)
    # Raw bytes live in S3; Postgres holds the pointer only (Architecture.md §5).
    s3_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    uploaded_at: Mapped[datetime.datetime] = mapped_column(
        TZDateTime(),
        nullable=False,
        server_default=utcnow(),
        default=lambda: datetime.datetime.now(datetime.UTC),
    )

    project: Mapped[Project] = relationship(back_populates="documents")
    versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentVersion(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "document_versions"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    diff_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB(), nullable=True)

    document: Mapped[Document] = relationship(back_populates="versions")
