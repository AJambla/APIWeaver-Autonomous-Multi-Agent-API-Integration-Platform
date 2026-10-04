"""Dead-letter sink for failed workflow stage tasks."""

from __future__ import annotations

import asyncio
from typing import Any

from celery import Task

from app.core.logging import get_logger

logger = get_logger(__name__)


class DeadLetterTask(Task):
    """Consume dead-letter records from the `dlq` queue and log them.

    The record is the unit of inspection for failed stage tasks (the DLQ is
    log-structured, not a database table). A failure while recording must
    never republish — that would loop forever.
    """

    name = "agent_worker.tasks.dead_letter"

    def run(self, record: dict[str, Any]) -> dict[str, bool]:
        return asyncio.run(self.run_async(record))

    async def run_async(self, record: dict[str, Any]) -> dict[str, bool]:
        logger.error("agent_task_dead_letter", **record)
        return {"recorded": True}

    def on_failure(
        self,
        exc: Exception,
        task_id: str,
        args: tuple,
        kwargs: dict,
        einfo: Any,
    ) -> None:
        logger.error("dead_letter_recording_failed", task_id=task_id, error=str(exc))


dead_letter_task = DeadLetterTask()
