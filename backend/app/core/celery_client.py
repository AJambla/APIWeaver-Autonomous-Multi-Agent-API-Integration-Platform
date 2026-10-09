"""Broker-only Celery producer for the API process.

The API enqueues work by task *name*. It must not import `agent_worker`: that package is
not in the API image (built from `backend/`), and importing it would also pull every task
module and the whole agent pipeline into the web process. A bare `Celery` app with only a
broker URL is enough to publish a message that the worker's registered task consumes.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any

from celery import Celery

from app.core.config import Settings
from app.core.logging import request_id_ctx


@lru_cache(maxsize=4)
def get_producer(broker_url: str) -> Celery:
    """One producer per broker URL, reused across requests (it pools its connections)."""
    producer = Celery("apiweaver-api", broker=broker_url)
    producer.conf.update(
        task_serializer="json",
        accept_content=["json"],
        # Bound the publish: kombu otherwise retries a dead broker for a long time while
        # the request that triggered it waits.
        broker_connection_timeout=5,
        task_publish_retry_policy={"max_retries": 2, "interval_start": 0, "interval_step": 1},
    )
    return producer


async def send_task(
    settings: Settings, name: str, *, args: list[Any], task_id: str
) -> None:
    """Publish `name` to the worker without blocking the event loop.

    `Celery.send_task` is a synchronous kombu publish (with connection retries), so it runs
    in a thread rather than stalling every other request on this worker.
    """
    producer = get_producer(settings.celery_broker_url)
    # The worker binds this into its log context, so one request id follows the work from
    # the HTTP request through the broker into every agent log line.
    headers = {"request_id": request_id_ctx.get()} if request_id_ctx.get() else None
    await asyncio.to_thread(
        producer.send_task, name, args=args, task_id=task_id, headers=headers
    )
