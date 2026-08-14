"""partitioned high-volume tables — Database.md §3.16, §3.28

`agent_events` (monthly) and `usage_metrics` (daily) are declared as partitioned tables
in `Database.md`. SQLAlchemy's DDL layer cannot express `PARTITION BY RANGE`, so they are
created here with `op.execute()`.

On raw SQL: `Security.md §11` forbids string-concatenated SQL built from *request data*.
Every statement below is a static DDL constant or is interpolated only from values this
module computes itself (a revision-fixed date range and a table name from a local
tuple) — no request data reaches these strings, and the whole file is reviewed as part
of the migration.

Note the composite primary keys. Postgres requires the partition key to participate in
every unique constraint on a partitioned table, so the PK is `(id, created_at)` rather
than `id` alone. `id` remains globally unique because all partitions share one sequence.

Partition *maintenance* (rolling new partitions forward, retention, rollup to S3) is
deferred to Phase 6 via `pg_partman` per `Database.md §9`. Until then the pre-created
partitions below cover the near term and a `DEFAULT` partition catches everything else,
so an insert can never fail for want of a partition.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence
from datetime import date

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Pinned at authoring time, not computed from "today". A migration must produce identical
# schema whenever it runs — deriving partition bounds from the clock would make the
# result depend on the deploy date, so staging and production could diverge.
# Phase 6's pg_partman takes over rolling these forward.
_FIRST_MONTH = date(2026, 8, 1)
_MONTHS_TO_CREATE = 6
_FIRST_DAY = date(2026, 8, 1)
_DAYS_TO_CREATE = 31


def _month_starts(start: date, count: int) -> list[tuple[date, date]]:
    """`count` consecutive [month_start, next_month_start) ranges."""
    ranges: list[tuple[date, date]] = []
    year, month = start.year, start.month
    for _ in range(count):
        lower = date(year, month, 1)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        ranges.append((lower, date(year, month, 1)))
    return ranges


def _day_starts(start: date, count: int) -> list[tuple[date, date]]:
    """`count` consecutive [day, next_day) ranges."""
    ordinal = start.toordinal()
    return [
        (date.fromordinal(ordinal + offset), date.fromordinal(ordinal + offset + 1))
        for offset in range(count)
    ]


def upgrade() -> None:
    # --- agent_events (Database.md §3.16) ------------------------------------------
    op.execute(
        """
        CREATE TABLE agent_events (
            id              BIGSERIAL       NOT NULL,
            created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
            workflow_run_id UUID            NOT NULL,
            agent_name      VARCHAR(100)    NOT NULL,
            event_type      VARCHAR(50)     NOT NULL,
            payload         JSONB,
            CONSTRAINT pk_agent_events PRIMARY KEY (id, created_at),
            CONSTRAINT fk_agent_events_workflow_run_id_workflow_runs
                FOREIGN KEY (workflow_run_id)
                REFERENCES workflow_runs (id) ON DELETE CASCADE
        ) PARTITION BY RANGE (created_at)
        """
    )
    op.execute("CREATE INDEX idx_agent_events_run_id ON agent_events (workflow_run_id)")
    op.execute("CREATE INDEX idx_agent_events_created_at ON agent_events (created_at)")

    for lower, upper in _month_starts(_FIRST_MONTH, _MONTHS_TO_CREATE):
        op.execute(
            f"CREATE TABLE agent_events_{lower:%Y%m} PARTITION OF agent_events "
            f"FOR VALUES FROM ('{lower:%Y-%m-%d}') TO ('{upper:%Y-%m-%d}')"
        )
    # Catch-all so a row outside the pre-created range still inserts.
    op.execute("CREATE TABLE agent_events_default PARTITION OF agent_events DEFAULT")

    # --- usage_metrics (Database.md §3.28) -----------------------------------------
    op.execute(
        """
        CREATE TABLE usage_metrics (
            id              BIGSERIAL       NOT NULL,
            recorded_at     TIMESTAMPTZ     NOT NULL DEFAULT now(),
            organization_id UUID            NOT NULL,
            metric_name     VARCHAR(100)    NOT NULL,
            value           NUMERIC(18,4)   NOT NULL,
            CONSTRAINT pk_usage_metrics PRIMARY KEY (id, recorded_at),
            CONSTRAINT fk_usage_metrics_organization_id_organizations
                FOREIGN KEY (organization_id)
                REFERENCES organizations (id) ON DELETE CASCADE
        ) PARTITION BY RANGE (recorded_at)
        """
    )
    op.execute("CREATE INDEX idx_usage_metrics_org_id ON usage_metrics (organization_id)")
    op.execute("CREATE INDEX idx_usage_metrics_metric_name ON usage_metrics (metric_name)")

    for lower, upper in _day_starts(_FIRST_DAY, _DAYS_TO_CREATE):
        op.execute(
            f"CREATE TABLE usage_metrics_{lower:%Y%m%d} PARTITION OF usage_metrics "
            f"FOR VALUES FROM ('{lower:%Y-%m-%d}') TO ('{upper:%Y-%m-%d}')"
        )
    op.execute("CREATE TABLE usage_metrics_default PARTITION OF usage_metrics DEFAULT")


def downgrade() -> None:
    # Dropping the partitioned parent drops every attached partition with it.
    op.execute("DROP TABLE IF EXISTS usage_metrics")
    op.execute("DROP TABLE IF EXISTS agent_events")
