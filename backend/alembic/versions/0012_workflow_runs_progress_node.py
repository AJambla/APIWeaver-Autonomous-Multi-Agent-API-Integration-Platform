"""Add current_node and progress_percent to workflow_runs.

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("current_node", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "workflow_runs",
        sa.Column("progress_percent", sa.Integer(), nullable=True, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("workflow_runs", "progress_percent")
    op.drop_column("workflow_runs", "current_node")
