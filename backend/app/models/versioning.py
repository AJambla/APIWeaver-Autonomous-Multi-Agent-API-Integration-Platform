"""`artifact_versions` — Database.md §3.27.

Backs `GET /projects/{id}/versions` and the rollback endpoint (API.md §6.9).
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class ArtifactVersion(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "artifact_versions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "artifact_type",
            "version_number",
            name="uniq_artifact_versions_project_type_number",
        ),
        Index("idx_artifact_versions_project_id", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(String(50), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    diff_ref: Mapped[str | None] = mapped_column(String(1000), nullable=True)
