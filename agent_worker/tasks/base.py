"""Shared Celery task primitives for async workflow stages."""

from __future__ import annotations

import asyncio
from typing import Any

from celery import Task

from app.core.logging import get_logger

logger = get_logger(__name__)

_NOT_RUN = object()


def _send_dead_letter(app: Any, record: dict[str, Any]) -> None:
    """Publish a failed-task record onto the dedicated dlq queue."""
    app.send_task("agent_worker.tasks.dead_letter", args=[record], queue="dlq")


class AsyncTask(Task):
    """Run an async task implementation in Celery's synchronous task boundary.

    Redelivery-safe: workers ack late, so a crashed worker re-queues the
    message, and a task id that already completed returns its cached result
    instead of re-executing the stage.
    """

    def _completed_result(self) -> Any:
        if not self.request.id:
            return _NOT_RUN
        from celery.result import AsyncResult  # lazy: lets tests patch the lookup

        result = AsyncResult(self.request.id, app=self.app)
        if result.state == "SUCCESS":
            return result.result
        return _NOT_RUN

    def run(self, *args: Any, **kwargs: Any) -> Any:
        cached = self._completed_result()
        if cached is not _NOT_RUN:
            logger.info("task_result_reused", task_id=self.request.id)
            return cached
        return asyncio.run(self.run_async(*args, **kwargs))

    async def run_async(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def on_failure(
        self,
        exc: Exception,
        task_id: str,
        args: tuple,
        kwargs: dict,
        einfo: Any,
    ) -> None:
        record = {
            "task": self.name,
            "task_id": task_id,
            "args": repr(args)[:2000],
            "kwargs": repr(kwargs)[:2000],
            "error": f"{type(exc).__name__}: {exc}",
        }
        logger.error("task_dead_letter", **record)
        try:
            _send_dead_letter(self.app, record)
        except Exception as publish_error:
            logger.error(
                "dead_letter_publish_failed", task_id=task_id, error=str(publish_error)
            )
