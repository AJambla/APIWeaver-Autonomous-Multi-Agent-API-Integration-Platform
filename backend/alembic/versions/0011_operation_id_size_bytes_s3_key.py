"""Add operation_id to endpoints, size_bytes to generated_files, and s3_key to exports.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "endpoints",
        sa.Column("operation_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "generated_files",
        sa.Column("size_bytes", sa.Integer(), nullable=True, server_default=sa.text("0")),
    )
    op.add_column(
        "exports",
        sa.Column("s3_key", sa.String(length=1000), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("exports", "s3_key")
    op.drop_column("generated_files", "size_bytes")
    op.drop_column("endpoints", "operation_id")
