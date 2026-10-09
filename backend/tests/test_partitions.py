"""Partition maintenance on a real Postgres (partitioned DDL is Postgres-only).

Run with a scratch database migrated to head, as CI does:

    AUDIT_PG_TEST_URL=postgresql+asyncpg://user:pass@127.0.0.1:5432/scratch pytest tests/test_partitions.py
"""

from __future__ import annotations

import datetime
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.partitions import ensure_partitions

PG_TEST_URL = os.environ.get("AUDIT_PG_TEST_URL", "")

pytestmark = pytest.mark.skipif(not PG_TEST_URL, reason="set AUDIT_PG_TEST_URL to run")


async def test_rows_stranded_in_default_move_into_new_monthly_partitions() -> None:
    engine = create_async_engine(PG_TEST_URL)
    org_id = uuid.uuid4()
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO organizations (id, name, slug) VALUES (:id, 'p', :slug)"),
                {"id": org_id, "slug": f"p-{org_id.hex[:8]}"},
            )
            # September/October 2026 had no partition: these land in usage_metrics_default.
            await conn.execute(
                text(
                    "INSERT INTO usage_metrics (organization_id, metric_name, value, recorded_at) "
                    "VALUES (:o, 'token_cost_usd', 1, '2026-09-15'), "
                    "(:o, 'token_cost_usd', 2, '2026-10-02')"
                ),
                {"o": org_id},
            )

        created = await ensure_partitions(engine, today=datetime.date(2026, 10, 9))

        assert "usage_metrics_202609" in created and "usage_metrics_202610" in created
        assert "usage_metrics_202601" not in created  # nothing before where 0002 stopped
        async with engine.connect() as conn:
            stranded = await conn.scalar(
                text("SELECT count(*) FROM usage_metrics_default WHERE organization_id = :o"),
                {"o": org_id},
            )
            by_partition = dict(
                (
                    await conn.execute(
                        text(
                            "SELECT tableoid::regclass::text, value FROM usage_metrics "
                            "WHERE organization_id = :o"
                        ),
                        {"o": org_id},
                    )
                ).all()
            )
        assert stranded == 0
        assert by_partition == {"usage_metrics_202609": 1, "usage_metrics_202610": 2}

        # Idempotent, and the horizon is three months ahead.
        assert await ensure_partitions(engine, today=datetime.date(2026, 10, 9)) == []
        async with engine.connect() as conn:
            assert await conn.scalar(text("SELECT to_regclass('usage_metrics_202701')")) is not None
            assert await conn.scalar(text("SELECT to_regclass('agent_events_202701')")) is not None
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM usage_metrics WHERE organization_id = :o"), {"o": org_id})
            await conn.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org_id})
        await engine.dispose()
