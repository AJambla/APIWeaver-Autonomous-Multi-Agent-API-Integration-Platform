"""add the missing test_runs status and summary columns

`TestRun` has declared both columns since the model was written, but neither
ever reached the database, so every insert into `test_runs` failed with
`column "status" of relation "test_runs" does not exist` and
`POST /projects/{id}/test` answered 500.

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db.base import JSONB

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing rows need a value for the NOT NULL column; the model's own default is "pending".
    op.add_column(
        "test_runs",
        sa.Column(
            "status",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
    )
    op.add_column("test_runs", sa.Column("summary", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("test_runs", "summary")
    op.drop_column("test_runs", "status")
