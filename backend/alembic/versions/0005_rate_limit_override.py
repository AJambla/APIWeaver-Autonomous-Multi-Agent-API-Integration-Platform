"""add_rate_limit_override — Task 7.2 Enterprise Rate Limit Overrides

Adds `rate_limit_override` nullable integer column to `organizations` table
for per-org custom rate limits (`API.md §3` Enterprise tier "Custom").

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "rate_limit_override",
            sa.Integer(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("organizations", "rate_limit_override")