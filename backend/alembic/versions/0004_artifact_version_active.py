"""add_artifact_version_is_active — Phase 5 versioning rollback

Adds `is_active` boolean column to `artifact_versions` table to support
rollback to a previous version (`API.md §6.9`).

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add is_active column, defaulting to False
    op.add_column(
        "artifact_versions",
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("FALSE"),
            nullable=False,
        ),
    )
    # Partial index ensures at most one active version per (project, type)
    op.create_index(
        "idx_artifact_versions_active",
        "artifact_versions",
        ["project_id", "artifact_type"],
        unique=False,
        postgresql_where=sa.text("is_active = TRUE"),
    )


def downgrade() -> None:
    op.drop_index("idx_artifact_versions_active", table_name="artifact_versions")
    op.drop_column("artifact_versions", "is_active")