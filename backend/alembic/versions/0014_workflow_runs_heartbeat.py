"""Add the run lease column workflow_runs.heartbeat_at.

Revision ID: 0014
Revises: 0013
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    # The reaper scans executing and queued runs by lease age.
    op.create_index(
        "idx_workflow_runs_status_heartbeat",
        "workflow_runs",
        ["status", "heartbeat_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_workflow_runs_status_heartbeat", table_name="workflow_runs")
    op.drop_column("workflow_runs", "heartbeat_at")
