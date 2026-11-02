"""add_foreign_key_indexes

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-02 10:45:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index('ix_organization_members_user_id', 'organization_members', ['user_id'], unique=False)
    op.create_index('ix_project_members_user_id', 'project_members', ['user_id'], unique=False)
    op.create_index('ix_api_specs_source_document_id', 'api_specs', ['source_document_id'], unique=False)
    op.create_index('ix_test_runs_workflow_run_id', 'test_runs', ['workflow_run_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_test_runs_workflow_run_id', table_name='test_runs')
    op.drop_index('ix_api_specs_source_document_id', table_name='api_specs')
    op.drop_index('ix_project_members_user_id', table_name='project_members')
    op.drop_index('ix_organization_members_user_id', table_name='organization_members')
