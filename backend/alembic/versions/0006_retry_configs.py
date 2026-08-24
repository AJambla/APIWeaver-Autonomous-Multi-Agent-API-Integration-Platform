"""create_retry_configs — Task 7.3 Retry Policy Config API

Creates `retry_configs` table for per-project retry policy configuration
matching frontend `RetryPolicy` interface (`max_attempts`, `backoff_base_seconds`,
`retryable_status_codes`).

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "retry_configs",
        sa.Column("id", sa.UUID(), nullable=False, primary_key=True),
        sa.Column(
            "project_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column(
            "backoff_base_seconds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("2"),
        ),
        sa.Column(
            "retryable_status_codes",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[429, 500, 502, 503, 504]'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("retry_configs")