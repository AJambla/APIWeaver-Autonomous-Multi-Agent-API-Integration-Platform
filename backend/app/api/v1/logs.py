"""Logs API route (`Feature.md §16`)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.models.project import Project
from app.models.workflow import AgentEvent, WorkflowRun
from app.rbac.enforce import require_project_permission
from app.rbac.policy import Permission
from app.schemas.common import Page, PaginationMeta, decode_cursor, encode_cursor

router = APIRouter(tags=["logs"])


@router.get("/projects/{id}/logs", response_model=Page[dict])
async def get_project_logs(
    id: uuid.UUID,
    project: Project = Depends(require_project_permission(Permission.WORKFLOW_READ)),
    session: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
) -> Page[dict]:
    """Paginated agent events for a project."""
    stmt = (
        select(AgentEvent)
        .join(WorkflowRun, AgentEvent.workflow_run_id == WorkflowRun.id)
        .where(WorkflowRun.project_id == project.id)
    )

    if cursor and (position := decode_cursor(cursor)):
        try:
            last_created = position["created_at"]
            last_id = position["id"]
            stmt = stmt.where(
                (AgentEvent.created_at, AgentEvent.id) < (last_created, last_id)
            )
        except (KeyError, TypeError, ValueError):
            pass

    stmt = stmt.order_by(AgentEvent.created_at.desc(), AgentEvent.id.desc()).limit(limit + 1)
    rows = list((await session.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    page_rows = rows[:limit]

    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor({"created_at": last.created_at.isoformat(), "id": str(last.id)})

    items = [
        {
            "id": str(row.id),
            "event_type": row.event_type,
            "agent_name": row.agent_name,
            "payload": row.payload,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in page_rows
    ]

    return Page[dict](
        data=items,
        pagination=PaginationMeta(next_cursor=next_cursor, has_more=has_more, limit=limit),
    )
