"""add_github_oauth_and_connections — Phase 4 GitHub integration

Creates the two tables defined in `app/models/github.py`:
- `github_oauth_states` — CSRF tokens for the OAuth authorization flow
- `github_connections` — user-to-GitHub account bindings

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db.base import UUID, TZDateTime, gen_random_uuid, utcnow

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "github_oauth_states",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("user_id", UUID(), nullable=False),
        sa.Column("state", sa.String(64), nullable=False),
        sa.Column("expires_at", TZDateTime(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_github_oauth_states_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_github_oauth_states"),
        sa.UniqueConstraint("state", name="uq_github_oauth_states_state"),
    )
    op.create_index("idx_github_oauth_states_user_id", "github_oauth_states", ["user_id"])
    op.create_index("idx_github_oauth_states_expires_at", "github_oauth_states", ["expires_at"])

    op.create_table(
        "github_connections",
        sa.Column("id", UUID(), server_default=gen_random_uuid(), nullable=False),
        sa.Column("user_id", UUID(), nullable=False),
        sa.Column("github_user_id", sa.String(64), nullable=False),
        sa.Column("github_username", sa.String(255), nullable=False),
        sa.Column("access_token_vault_path", sa.String(500), nullable=True),
        sa.Column("refresh_token_vault_path", sa.String(500), nullable=True),
        sa.Column("scopes_granted", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("revoked_at", TZDateTime(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=utcnow(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_github_connections_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_github_connections"),
        sa.UniqueConstraint(
            "user_id", "github_user_id", name="uniq_github_conn_user_github"
        ),
    )
    op.create_index("idx_github_connections_user_id", "github_connections", ["user_id"])


def downgrade() -> None:
    op.drop_table("github_connections")
    op.drop_table("github_oauth_states")
