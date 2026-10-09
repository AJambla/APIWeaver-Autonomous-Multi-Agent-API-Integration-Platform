"""Logs API route (`Feature.md §16`)."""

from __future__ import annotations

import datetime
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import literal, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.logging import get_logger
from app.models.project import Project
from app.models.workflow import AgentEvent, WorkflowRun
from app.rbac.enforce import require_project_permission
from app.rbac.policy import Permission
from app.schemas.common import Page, PaginationMeta, decode_cursor, encode_cursor

router = APIRouter(tags=["logs"])
logger = get_logger(__name__)


@router.get("/projects/{id}/logs", response_model=Page[dict])
async def get_project_logs(
    id: uuid.UUID,
    project: Project = Depends(require_project_permission(Permission.WORKFLOW_READ)),
    session: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    run_id: uuid.UUID | None = Query(default=None, description="Only this run's events"),
) -> Page[dict]:
    """Paginated agent events for a project, optionally narrowed to one run."""
    stmt = (
        select(AgentEvent)
        .join(WorkflowRun, AgentEvent.workflow_run_id == WorkflowRun.id)
        .where(WorkflowRun.project_id == project.id)
    )
    if run_id is not None:
        stmt = stmt.where(AgentEvent.workflow_run_id == run_id)

    if cursor and (position := decode_cursor(cursor)):
        try:
            last_created = datetime.datetime.fromisoformat(position["created_at"])
            last_id = int(position["id"])
        except (KeyError, TypeError, ValueError) as exc:
            logger.debug("logs_cursor_invalid", cursor=cursor, error=str(exc))
        else:
            # A Python tuple comparison here compiled to `created_at < '<iso string>'`
            # and failed on every second page; tuple_ is the SQL row-value compare.
            stmt = stmt.where(
                tuple_(AgentEvent.created_at, AgentEvent.id) < tuple_(literal(last_created), literal(last_id))
            )

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
            "workflow_run_id": str(row.workflow_run_id) if row.workflow_run_id else None,
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
