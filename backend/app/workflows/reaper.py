"""Fail workflow runs that can no longer finish.

Two ways a run used to stay "running" or "queued" forever:

* Its executor died. A hard time limit, an OOM kill or a deploy's SIGKILL never reaches
  `RunWorkflow.on_failure` (Celery handles those in the parent process), and the
  redelivered message is refused by the orchestrator's claim, by design.
* Nothing ever picked it up (the broker message was lost, or no worker was running).

The orchestrator refreshes `heartbeat_at` while a run executes; a RUNNING run silent for
longer than the lease lost its executor, and a QUEUED run older than the queue timeout was
never claimed. Both are marked FAILED so the UI and the user can act on them. Every
replica may run this: each update is conditional and idempotent.
"""

from __future__ import annotations

import asyncio
import datetime

from sqlalchemy import and_, func, or_, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.metrics import pipeline_error_total
from app.models.enums import WorkflowStatus
from app.models.workflow import WorkflowRun

logger = get_logger(__name__)


async def reap_stale_runs(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    now: datetime.datetime | None = None,
) -> int:
    """Mark lost and never-claimed runs FAILED. Returns how many were reaped."""
    now = now or datetime.datetime.now(datetime.UTC)
    lease_cutoff = now - datetime.timedelta(seconds=settings.workflow_lease_seconds)
    queue_cutoff = now - datetime.timedelta(seconds=settings.workflow_queue_timeout_seconds)
    last_seen = func.coalesce(WorkflowRun.heartbeat_at, WorkflowRun.started_at, WorkflowRun.created_at)
    queued_since = func.coalesce(WorkflowRun.heartbeat_at, WorkflowRun.created_at)

    async with session_factory() as session:
        result = await session.execute(
            update(WorkflowRun)
            .where(
                or_(
                    and_(WorkflowRun.status == WorkflowStatus.RUNNING, last_seen < lease_cutoff),
                    and_(WorkflowRun.status == WorkflowStatus.QUEUED, queued_since < queue_cutoff),
                )
            )
            .values(
                status=WorkflowStatus.FAILED,
                completed_at=now,
                current_node="executor_lost",
            )
            .returning(WorkflowRun.id)
            .execution_options(synchronize_session=False)
        )
        reaped = [str(run_id) for run_id in result.scalars()]
        await session.commit()

    if reaped:
        pipeline_error_total.labels(subsystem="workflow_reaper", error_type="executor_lost").inc(
            len(reaped)
        )
        logger.warning("workflow_runs_reaped", count=len(reaped), run_ids=reaped[:50])
    return len(reaped)


async def run_reaper_forever(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """Background loop for the API process lifespan."""
    interval = max(5, settings.workflow_reaper_interval_seconds)
    while True:
        try:
            await reap_stale_runs(session_factory, settings)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - keep the loop alive across DB blips
            logger.warning("workflow_reaper_failed", error=str(exc))
        await asyncio.sleep(interval)
