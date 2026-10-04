"""AgentEvent / ToolCall persistence backing the logs and tool-calls APIs.

The orchestrator and agents emit structured trace events through `record_agent_event`;
each event and its tool calls are written in the caller's transaction so the
`ToolCall.agent_event_id` linkage always resolves (ADDENDUM-Phase1.md §A.4).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import AgentEvent, ToolCall


async def record_agent_event(
    session: AsyncSession,
    *,
    workflow_run_id: uuid.UUID,
    agent_name: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
) -> int:
    """Write one agent trace event, optionally with its tool calls.

    Returns the event id.
    """
    event = AgentEvent(
        workflow_run_id=workflow_run_id,
        agent_name=agent_name,
        event_type=event_type,
        payload=payload,
    )
    session.add(event)
    await session.flush()

    for call in tool_calls or []:
        session.add(
            ToolCall(
                agent_event_id=event.id,
                tool_name=str(call.get("tool_name", "unknown")),
                arguments=call.get("arguments"),
                result=call.get("result"),
                duration_ms=call.get("duration_ms"),
            )
        )

    if tool_calls:
        await session.flush()
    return int(event.id)
