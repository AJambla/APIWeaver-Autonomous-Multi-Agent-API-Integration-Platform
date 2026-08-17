"""Redis Streams event publisher for workflow and project events."""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class EventPublisher:
    """Publishes workflow lifecycle events to Redis Streams.

    Events are written to two stream families:
    - `workflow_events:{run_id}` — per-run stream for WebSocket/SSE subscribers.
    - `project_events:{project_id}` — per-project stream for project-level dashboards.
    """

    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client
        self._settings = get_settings()

    async def publish(
        self,
        run_id: str,
        project_id: str | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        """Write an event to both the run and project Redis Streams."""
        message = {
            "event_type": event_type,
            "run_id": run_id,
            "payload": json.dumps(payload, default=str),
        }
        workflow_stream = f"workflow_events:{run_id}"
        project_stream = f"project_events:{project_id}" if project_id else None

        try:
            tasks = [self._redis.xadd(workflow_stream, message)]
            if project_stream:
                tasks.append(self._redis.xadd(project_stream, message))
            await tasks[0]
            if len(tasks) > 1:
                await tasks[1]
        except Exception:
            logger.warning("event_publish_failed", run_id=run_id, event_type=event_type)

    async def publish_workflow_started(
        self,
        run_id: str,
        project_id: str | None,
        stages: list[str],
    ) -> None:
        await self.publish(
            run_id,
            project_id,
            "workflow.started",
            {"stages": stages, "progress_percent": 0},
        )

    async def publish_workflow_progress(
        self,
        run_id: str,
        project_id: str | None,
        current_node: str,
        progress_percent: int,
    ) -> None:
        await self.publish(
            run_id,
            project_id,
            "workflow.progress",
            {"current_node": current_node, "progress_percent": progress_percent},
        )

    async def publish_node_completed(
        self,
        run_id: str,
        project_id: str | None,
        node_name: str,
        output_summary: dict[str, Any] | None = None,
    ) -> None:
        await self.publish(
            run_id,
            project_id,
            "node_completed",
            {"node_name": node_name, "output_summary": output_summary or {}},
        )

    async def publish_workflow_completed(
        self,
        run_id: str,
        project_id: str | None,
        status: str,
        result: dict[str, Any] | None = None,
    ) -> None:
        await self.publish(
            run_id,
            project_id,
            "workflow.completed",
            {"status": status, "progress_percent": 100, "result": result or {}},
        )

    async def publish_test_result(
        self,
        run_id: str,
        project_id: str | None,
        passed: int,
        failed: int,
        skipped: int,
        duration_ms: int,
    ) -> None:
        await self.publish(
            run_id,
            project_id,
            "test.result",
            {
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "duration_ms": duration_ms,
            },
        )

    async def publish_repair_attempt(
        self,
        run_id: str,
        project_id: str | None,
        attempt_number: int,
        outcome: str,
        node_name: str,
        error: str | None = None,
    ) -> None:
        await self.publish(
            run_id,
            project_id,
            "repair.attempt",
            {
                "attempt_number": attempt_number,
                "outcome": outcome,
                "node_name": node_name,
                "error": error,
            },
        )

    async def publish_export_progress(
        self,
        run_id: str,
        project_id: str | None,
        export_type: str,
        status: str,
        artifact_count: int = 0,
    ) -> None:
        await self.publish(
            run_id,
            project_id,
            "export.progress",
            {
                "export_type": export_type,
                "status": status,
                "artifact_count": artifact_count,
            },
        )
