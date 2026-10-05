"""Real-time workflow events via Server-Sent Events (SSE)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_principal, get_db, get_redis
from app.core.errors import NotFoundError
from app.models.workflow import WorkflowRun
from app.rbac.enforce import load_project_for_principal
from app.rbac.policy import Principal

router = APIRouter(tags=["events"])


async def _verify_run_access(
    session: AsyncSession,
    principal: Principal,
    run_id: Any,
) -> WorkflowRun:
    run = await session.get(WorkflowRun, run_id)
    if run is None:
        raise NotFoundError("Workflow run not found.")
    await load_project_for_principal(session, principal, run.project_id)
    return run


async def _stream_redis_events(
    redis_client: aioredis.Redis,
    stream_key: str,
    last_id: str,
    block_ms: int = 5000,
) -> AsyncIterator[str]:
    """Yield SSE-formatted events from a Redis Stream."""
    while True:
        try:
            results = await redis_client.xread(
                {stream_key: last_id},
                block=block_ms,
                count=10,
            )
        except asyncio.CancelledError:
            break
        except Exception:
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

        if not results:
            yield ": heartbeat\n\n"


@router.get("/workflows/{run_id}/sse", response_class=StreamingResponse)
async def stream_workflow_events(
    run_id: Any,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
    last_event_id: str = Query(default="0-0"),
) -> StreamingResponse:
    """Server-Sent Events stream for a workflow run."""
    await _verify_run_access(session, principal, run_id)
    stream_key = f"workflow_events:{run_id}"

    async def event_generator() -> AsyncIterator[str]:
        async for chunk in _stream_redis_events(redis_client, stream_key, last_event_id):
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

