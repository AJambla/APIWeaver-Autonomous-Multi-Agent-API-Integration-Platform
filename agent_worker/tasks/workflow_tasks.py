"""Celery task that runs a full workflow via LangGraph."""

from __future__ import annotations

import asyncio
import datetime
import os
from typing import Any, cast
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from agent_worker.tasks.base import AsyncTask
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Read from the environment (not Settings) so importing this module needs no database or
# Redis configuration; `Settings.workflow_task_time_limit_seconds` documents the variable.
_TIME_LIMIT = int(os.environ.get("WORKFLOW_TASK_TIME_LIMIT_SECONDS", "3600"))


class RunWorkflow(AsyncTask):
    name = "agent_worker.tasks.run_workflow"
    # A whole pipeline (LLM codegen, sandbox tests, up to three repairs) outlives the
    # five-minute default every stage task uses; the soft limit leaves time to record
    # the failure before the hard kill.
    time_limit = _TIME_LIMIT
    soft_time_limit = max(_TIME_LIMIT - 60, 60)
    autoretry_for = (ConnectionError, TimeoutError, OSError)
    max_retries = 3
    retry_backoff = True
    retry_jitter = True

    async def run_async(
        self,
        run_id: str,
        initial_state: dict,
        post_run: dict[str, Any] | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> dict:
        import redis.asyncio as aioredis

        from app.services.event_publisher import EventPublisher
        from app.workflows.dispatch import execute_run
        from app.workflows.state import WorkflowState

        settings = get_settings()
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        redis_client = aioredis.from_url(settings.redis_url)
        try:
            session_factory = async_sessionmaker(
                bind=engine, class_=AsyncSession, expire_on_commit=False
            )
            # Worker-run workflows publish live progress like in-process ones; without
            # a publisher the UI's event stream stayed silent for every queued run.
            result = await execute_run(
                UUID(run_id),
                cast(WorkflowState, initial_state),
                session_factory=session_factory,
                event_publisher=EventPublisher(redis_client),
                post_run=post_run,
                settings=settings,
            )
            return _json_safe(dict(result))
        finally:
            await redis_client.aclose()
            await engine.dispose()

    def on_failure(
        self,
        exc: Exception,
        task_id: str,
        args: tuple,
        kwargs: dict,
        einfo: Any,
    ) -> None:
        # A hard time limit or a crash never reaches the orchestrator's own failure
        # handling, which would leave the run RUNNING forever.
        run_id = args[0] if args and isinstance(args[0], str) else None
        if run_id:
            try:
                asyncio.run(_mark_run_failed(run_id, f"{type(exc).__name__}: {exc}"))
            except Exception as mark_error:
                logger.error("workflow_mark_failed_error", run_id=run_id, error=str(mark_error))
        super().on_failure(exc, task_id, args, kwargs, einfo)


async def _mark_run_failed(run_id: str, reason: str) -> None:
    from app.models.enums import WorkflowStatus
    from app.models.workflow import WorkflowRun

    engine = create_async_engine(get_settings().database_url)
    try:
        async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
            await session.execute(
                update(WorkflowRun)
                .where(
                    WorkflowRun.id == UUID(run_id),
                    WorkflowRun.status.in_([WorkflowStatus.RUNNING, WorkflowStatus.QUEUED]),
                )
                .values(
                    status=WorkflowStatus.FAILED,
                    completed_at=datetime.datetime.now(datetime.UTC),
                )
            )
            await session.commit()
        logger.error("workflow_marked_failed_by_worker", run_id=run_id, reason=reason)
    finally:
        await engine.dispose()


def _json_safe(value: Any) -> Any:
    """Celery's JSON result backend cannot store bytes, enums or UUIDs as-is."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items() if k != "raw_document_bytes"}
    if isinstance(value, list | tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, bytes):
        return None
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


run_workflow = RunWorkflow()
