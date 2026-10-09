"""Redis Streams event publisher for workflow and project events."""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis
from redis.typing import EncodableT, FieldT

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import pipeline_error_total

logger = get_logger(__name__)


class EventPublisher:
    """Publishes workflow lifecycle events to Redis Streams.

    Events are written to two stream families:
    - `workflow_events:{run_id}` — per-run stream for SSE subscribers.
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
        message: dict[FieldT, EncodableT] = {
            "event_type": event_type,
            "run_id": run_id,
            "payload": json.dumps(payload, default=str),
        }
        workflow_stream = f"workflow_events:{run_id}"
        project_stream = f"project_events:{project_id}" if project_id else None

        try:
            workflow_maxlen = self._settings.redis_stream_workflow_maxlen
            project_maxlen = self._settings.redis_stream_project_maxlen
            workflow_ttl = self._settings.redis_stream_workflow_ttl_seconds
            project_ttl = self._settings.redis_stream_project_ttl_seconds

            # Awaited one at a time. Both coroutines used to be created up front, so when the
            # first XADD raised, the second was never awaited (a "coroutine was never
            # awaited" warning and a silently dropped project-stream event).
            await self._redis.xadd(workflow_stream, message, maxlen=workflow_maxlen, approximate=True)
            if project_stream:
                await self._redis.xadd(project_stream, message, maxlen=project_maxlen, approximate=True)
            await self._redis.expire(workflow_stream, workflow_ttl)
            if project_stream:
                await self._redis.expire(project_stream, project_ttl)
        except Exception as exc:
            pipeline_error_total.labels(subsystem="event_publisher", error_type=type(exc).__name__).inc()
            logger.error("event_publish_failed", run_id=run_id, event_type=event_type, error=str(exc), exc_info=True)

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
        progress_percent: int | None = None,
    ) -> None:
        if progress_percent is None:
            if status == "completed":
                progress = 100
            elif status == "paused_for_approval":
                progress = 50
            elif status == "cancelled":
                progress = 0
            else:
                progress = 90
        else:
            progress = progress_percent

        await self.publish(
            run_id,
            project_id,
            "workflow.completed",
            {"status": status, "progress_percent": progress, "result": result or {}},
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

    async def publish_agent_thought(
        self,
        run_id: str,
        project_id: str | None,
        agent_name: str,
        message: str,
        level: str = "info",
        action: str | None = None,
        step: int | None = None,
        total_steps: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Publish real-time agent thought, activity, or sub-step update."""
        import datetime
        payload = {
            "agent_name": agent_name,
            "message": message,
            "level": level,
            "action": action,
            "step": step,
            "total_steps": total_steps,
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            **(extra or {}),
        }
        await self.publish(
            run_id,
            project_id,
            "agent.thought",
            payload,
        )
