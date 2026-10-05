"""enforce audit-log immutability in the database (audit M3)

`Security.md §17` asks for `audit_logs` to be "append-only at the database permission
level". Terraform carried that GRANT as a `null_resource` local-exec which
`EXCEPTION WHEN OTHERS` reduced to a notice — a missing table, a wrong role, or a refused
connection all reported success, and it never ran again. GRANT could not bind the table
owner either, which is the role both the Compose stack and the RDS module's default
`db_app_role` connect as, so the control was absent wherever it mattered.

Enforcement moves here: versioned, applied to every environment on the next
`alembic upgrade`, and a hard failure rather than a notice when it does not apply. A row
trigger binds every role that writes through SQL, including the owner and an over-granted
application role.

Referential actions are exempt. `organizations.id` cascades and `users.id` sets null, and
both are executed on `audit_logs` from inside the RI constraint triggers, where
`pg_trigger_depth()` reports 2 on PostgreSQL 16 — a statement the application issues
itself reports 1, so the comparison below blocks exactly the direct mutations and nothing
else. Verified against postgres:16.15 in `tests/test_audit_immutability.py`.

The gap this leaves is deployment-level, not schema-level: the table owner can
`ALTER TABLE audit_logs DISABLE TRIGGER ...` and a superuser can
`SET session_replication_role = replica`, and the Compose stack's `POSTGRES_USER` is both.
A non-owner application role closes it — such a role can neither drop nor disable this
trigger, and cannot TRUNCATE the table either, which a row trigger cannot intercept.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Static DDL only, with no `:` or `%` that a bind-parameter or pyformat paramstyle could
# misread, and no non-ASCII in the raised message so `alembic upgrade --sql` can print it
# on a Windows console.
_GUARD_FUNCTION = """
CREATE OR REPLACE FUNCTION audit_logs_append_only() RETURNS trigger
LANGUAGE plpgsql
AS $fn$
BEGIN
    IF pg_trigger_depth() > 1 THEN
        RETURN COALESCE(NEW, OLD);
    END IF;
    RAISE EXCEPTION USING
        MESSAGE = 'audit_logs is append-only: ' || TG_OP || ' is withheld at the database level',
        ERRCODE = 'insufficient_privilege';
END
$fn$
"""


def upgrade() -> None:
    op.execute(_GUARD_FUNCTION)
    op.execute(
        "CREATE TRIGGER audit_logs_no_update BEFORE UPDATE ON audit_logs "
        "FOR EACH ROW EXECUTE FUNCTION audit_logs_append_only()"
    )
    op.execute(
        "CREATE TRIGGER audit_logs_no_delete BEFORE DELETE ON audit_logs "
        "FOR EACH ROW EXECUTE FUNCTION audit_logs_append_only()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_logs_no_delete ON audit_logs")
    op.execute("DROP TRIGGER IF EXISTS audit_logs_no_update ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS audit_logs_append_only()")
