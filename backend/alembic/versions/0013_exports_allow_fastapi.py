"""Allow the `fastapi` export type in `exports.export_type`.

`ExportType.FASTAPI` exists and the export agent produces it, but 0001 created the CHECK
without it, so any export including `fastapi` (and the "all types" fallback) failed on
Postgres with a constraint violation.

Revision ID: 0013
Revises: 0012
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WITH_FASTAPI = "export_type IN ('sdk', 'client', 'fastapi', 'docker', 'github', 'mcp', 'docs', 'cicd')"
_WITHOUT_FASTAPI = "export_type IN ('sdk', 'client', 'docker', 'github', 'mcp', 'docs', 'cicd')"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_exports_export_type_valid"), "exports", type_="check")
    op.create_check_constraint(op.f("ck_exports_export_type_valid"), "exports", _WITH_FASTAPI)


def downgrade() -> None:
    op.execute("DELETE FROM exports WHERE export_type = 'fastapi'")
    op.drop_constraint(op.f("ck_exports_export_type_valid"), "exports", type_="check")
    op.create_check_constraint(op.f("ck_exports_export_type_valid"), "exports", _WITHOUT_FASTAPI)
