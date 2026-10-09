"""Real-time workflow events via Server-Sent Events (SSE)."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import AsyncIterator
from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_principal, get_db, get_stream_redis
from app.core.errors import NotFoundError, UnprocessableEntityError
from app.core.logging import get_logger
from app.core.metrics import pipeline_error_total
from app.models.enums import WorkflowStatus
from app.models.workflow import WorkflowRun
from app.rbac.enforce import assert_project_permission
from app.rbac.policy import Permission, Principal

logger = get_logger(__name__)

router = APIRouter(tags=["events"])


async def _verify_run_access(
    session: AsyncSession,
    principal: Principal,
    run_id: Any,
) -> WorkflowRun:
    try:
        run_uuid = run_id if isinstance(run_id, uuid.UUID) else uuid.UUID(str(run_id))
    except ValueError as exc:
        raise NotFoundError("Workflow run not found.") from exc
    run = await session.get(WorkflowRun, run_uuid)
    if run is None:
        raise NotFoundError("Workflow run not found.")
    # Live events carry thoughts, errors and tool output: the project role is required,
    # not just membership of the owning organization.
    await assert_project_permission(session, principal, Permission.WORKFLOW_READ, run.project_id)
    return run


# How long one XREAD parks waiting for events (main.py sizes the stream client's
# socket timeout above it).
SSE_BLOCK_MS = 5000


# A stream is closed after this long; the client resumes from its Last-Event-ID.
SSE_MAX_SECONDS = 3600
_STREAM_ID = re.compile(r"^\d+-\d+$")
_TERMINAL_EVENT_FOR_STATUS = {
    WorkflowStatus.COMPLETED: "workflow.completed",
    WorkflowStatus.FAILED: "workflow.failed",
    WorkflowStatus.CANCELLED: "workflow.cancelled",
}


async def _stream_redis_events(
    redis_client: aioredis.Redis,
    stream_key: str,
    last_id: str,
    block_ms: int = SSE_BLOCK_MS,
    *,
    finished_status: str | None = None,
    max_seconds: float = SSE_MAX_SECONDS,
) -> AsyncIterator[str]:
    """Yield SSE-formatted events from a Redis Stream.

    `finished_status` is the run's terminal status when the client connected. Once its
    events are replayed and the stream has nothing more, a synthetic terminal event
    closes the stream: when the stream had expired (TTL/MAXLEN) the client used to
    receive heartbeats forever for a run that ended long ago.
    """
    deadline = asyncio.get_running_loop().time() + max_seconds
    while True:
        if asyncio.get_running_loop().time() > deadline:
            return
        try:
            results = await redis_client.xread(
                {stream_key: last_id},
                block=block_ms,
                count=10,
            )
        except asyncio.CancelledError:
            break
        except Exception as exc:
            pipeline_error_total.labels(subsystem="sse_events", error_type=type(exc).__name__).inc()
            logger.error("sse_redis_read_failed", stream_key=stream_key, error=str(exc), exc_info=True)
            await asyncio.sleep(1)
            continue

        for stream, messages in results:
            for message_id, message_data in messages:
                last_id = message_id
                payload = message_data.get(b"payload", message_data.get("payload"))
                if payload is None:
                    continue
                if isinstance(payload, bytes):
                    payload = payload.decode("utf-8")
                event_type = message_data.get(
                    b"event_type", message_data.get("event_type", "message")
                )
                if isinstance(event_type, bytes):
                    event_type = event_type.decode("utf-8")
                yield f"event: {event_type}\ndata: {payload}\nid: {message_id}\n\n"
                if event_type in ("workflow.completed", "workflow.failed", "workflow.cancelled"):
                    return

        if not results:
            terminal_event = _TERMINAL_EVENT_FOR_STATUS.get(finished_status or "")
            if terminal_event:
                payload = json.dumps({"status": finished_status, "replayed": False})
                yield f"event: {terminal_event}\ndata: {payload}\n\n"
                return
            yield ": heartbeat\n\n"


@router.get("/workflows/{run_id}/sse", response_class=StreamingResponse)
async def stream_workflow_events(
    run_id: Any,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_stream_redis),
    last_event_id: str = Query(default="0-0"),
) -> StreamingResponse:
    """Server-Sent Events stream for a workflow run."""
    run = await _verify_run_access(session, principal, run_id)
    if not _STREAM_ID.fullmatch(last_event_id):
        # XREAD rejects anything else, and the generator used to retry that error once a
        # second for as long as the client stayed connected.
        raise UnprocessableEntityError("last_event_id must be a Redis stream id like 0-0.")
    # The canonical id, not the raw path segment: an upper-case or brace-wrapped UUID
    # passed the access check above but named a stream nobody writes to.
    stream_key = f"workflow_events:{run.id}"
    finished_status = run.status if run.status in _TERMINAL_EVENT_FOR_STATUS else None

    async def event_generator() -> AsyncIterator[str]:
        async for chunk in _stream_redis_events(
            redis_client, stream_key, last_event_id, finished_status=finished_status
        ):
            yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

