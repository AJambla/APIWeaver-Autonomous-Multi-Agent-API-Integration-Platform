"""`code_generation_runs`, `generated_files` — Database.md §3.18, §3.19."""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin
from app.models.enums import GeneratedFileType, TargetLanguage, check_in


class CodeGenerationRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "code_generation_runs"
    __table_args__ = (
        CheckConstraint(check_in("target_language", TargetLanguage), name="target_language_valid"),
        Index("idx_code_generation_runs_workflow_run_id", "workflow_run_id"),
    )

    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    target_language: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)

    files: Mapped[list[GeneratedFile]] = relationship(
        back_populates="code_generation_run", cascade="all, delete-orphan"
    )


class GeneratedFile(UUIDPrimaryKeyMixin, Base):
    """Metadata only — file bodies stream to S3 (Architecture.md §5 step 3)."""

    __tablename__ = "generated_files"
    __table_args__ = (
        CheckConstraint(check_in("file_type", GeneratedFileType), name="file_type_valid"),
        Index("idx_generated_files_run_id", "code_generation_run_id"),
    )

    code_generation_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("code_generation_runs.id", ondelete="CASCADE"), nullable=False
    )
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    content_s3_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    file_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    code_generation_run: Mapped[CodeGenerationRun] = relationship(back_populates="files")
