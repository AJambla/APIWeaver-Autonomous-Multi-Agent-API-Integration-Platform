"""Roll the range partitions of `agent_events` and `usage_metrics` forward.

Migration 0002 pins the partitions it creates (a migration must not depend on the deploy
date) and leaves "rolling forward" to later maintenance, which never existed: since
2026-09-01 every `usage_metrics` row has landed in `usage_metrics_default`, and
`agent_events` runs out on 2027-02-01. Inserts never fail (the DEFAULT partitions catch
them), but nothing is pruned, the default partitions grow without bound, and Postgres
refuses to create a partition for a range that already has rows in DEFAULT.

`ensure_partitions` creates one monthly partition per table from where 0002 stopped up to
`months_ahead` past today. A range whose rows already sit in DEFAULT is created
standalone, filled from DEFAULT, purged from DEFAULT and then attached, all in one
transaction, so no row is lost or duplicated. Retention (dropping old partitions) is a
data-policy decision and is deliberately not done here.

Postgres only; a no-op on SQLite. Table and partition names come from the constants
below and dates computed here, never from request data (Security.md §11).
"""

from __future__ import annotations

import datetime
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.logging import get_logger

logger = get_logger(__name__)

# (table, partition key column, first month 0002 does not cover)
_PARTITIONED: tuple[tuple[str, str, datetime.date], ...] = (
    ("agent_events", "created_at", datetime.date(2027, 2, 1)),
    # 0002 created daily partitions for August 2026 only; monthly from September on.
    ("usage_metrics", "recorded_at", datetime.date(2026, 9, 1)),
)

# Any constant shared by all replicas: only one of them does the work at a time.
_ADVISORY_LOCK_KEY = 0x41505750  # "APWP"


def _next_month(day: datetime.date) -> datetime.date:
    return datetime.date(day.year + (day.month == 12), day.month % 12 + 1, 1)


def _months(first: datetime.date, last: datetime.date) -> list[tuple[datetime.date, datetime.date]]:
    ranges = []
    lower = first
    while lower <= last:
        upper = _next_month(lower)
        ranges.append((lower, upper))
        lower = upper
    return ranges


async def ensure_partitions(
    engine: AsyncEngine, *, today: datetime.date | None = None, months_ahead: int = 3
) -> list[str]:
    """Create any missing monthly partitions; returns the names created."""
    if engine.dialect.name != "postgresql":
        return []
    today = today or datetime.datetime.now(datetime.UTC).date()
    horizon = datetime.date(today.year, today.month, 1)
    for _ in range(months_ahead):
        horizon = _next_month(horizon)

    created: list[str] = []
    async with engine.begin() as conn:
        got_lock = await conn.scalar(
            text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": _ADVISORY_LOCK_KEY}
        )
        if not got_lock:
            return created
        for table, column, first in _PARTITIONED:
            for lower, upper in _months(first, horizon):
                name = f"{table}_{lower:%Y%m}"
                exists = await conn.scalar(text("SELECT to_regclass(:name)"), {"name": name})
                if exists is not None:
                    continue
                bounds = f"FROM ('{lower:%Y-%m-%d}') TO ('{upper:%Y-%m-%d}')"
                in_range = f"{column} >= '{lower:%Y-%m-%d}' AND {column} < '{upper:%Y-%m-%d}'"
                await conn.execute(
                    text(f"CREATE TABLE {name} (LIKE {table} INCLUDING DEFAULTS INCLUDING CONSTRAINTS)")
                )
                moved = cast(CursorResult[Any], await conn.execute(
                    text(
                        f"WITH moved AS (DELETE FROM {table}_default WHERE {in_range} RETURNING *) "
                        f"INSERT INTO {name} SELECT * FROM moved"
                    )
                ))
                await conn.execute(text(f"ALTER TABLE {table} ATTACH PARTITION {name} FOR VALUES {bounds}"))
                created.append(name)
                logger.info("partition_created", partition=name, rows_moved=moved.rowcount)
    return created


async def run_partition_maintenance_forever(
    engine: AsyncEngine, *, interval_seconds: int = 6 * 3600
) -> None:
    """Background loop for the API lifespan: at startup, then every few hours."""
    import asyncio

    while True:
        try:
            await ensure_partitions(engine)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - retried next interval
            logger.warning("partition_maintenance_failed", error=str(exc))
        await asyncio.sleep(interval_seconds)
