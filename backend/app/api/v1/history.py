"""History and versioning API routes (`API.md §6.9`)."""

from __future__ import annotations

import datetime
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_principal, get_db
from app.core.errors import NotFoundError, UnprocessableEntityError
from app.models.enums import ActorType
from app.models.project import Project
from app.models.versioning import ArtifactVersion
from app.models.workflow import WorkflowRun
from app.rbac.enforce import require_project_permission
from app.rbac.policy import Permission, Principal
from app.schemas.history import (
    ArtifactVersionResponse,
    ArtifactVersionsResponse,
    HistoryResponse,
    RollbackResponse,
    WorkflowRunSummary,
)
from app.services import audit_service

router = APIRouter(prefix="/projects", tags=["history"])


@router.get("/{id}/history", response_model=HistoryResponse)
async def get_project_history(
    project: Project = Depends(require_project_permission(Permission.HISTORY_READ)),
    session: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    status_filter: str | None = Query(default=None, alias="status"),
    start_date: datetime.datetime | None = Query(default=None),
    end_date: datetime.datetime | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> HistoryResponse:
    """Paginated list of workflow runs for the project."""
    stmt = (
        select(WorkflowRun)
        .where(WorkflowRun.project_id == project.id)
        .order_by(WorkflowRun.started_at.desc().nulls_last())
    )

    if status_filter is not None:
        stmt = stmt.where(WorkflowRun.status == status_filter)
    if start_date is not None:
        stmt = stmt.where(WorkflowRun.started_at >= start_date)
    if end_date is not None:
        stmt = stmt.where(WorkflowRun.started_at <= end_date)

    if cursor:
        try:
            cursor_dt = datetime.datetime.fromisoformat(cursor)
            stmt = stmt.where(WorkflowRun.started_at < cursor_dt)
        except ValueError:
            pass

    stmt = stmt.limit(limit + 1)
    rows = list((await session.execute(stmt)).scalars())

    has_more = len(rows) > limit
    data = rows[:limit]

    next_cursor = None
    if has_more and data:
        last = data[-1]
        if last.started_at:
            next_cursor = last.started_at.isoformat()

    return HistoryResponse(
        data=[
            WorkflowRunSummary(
                id=run.id,
                status=run.status,
                started_at=run.started_at,
                completed_at=run.completed_at,
                total_tokens_used=run.total_tokens_used,
                estimated_cost_usd=float(run.estimated_cost_usd),
            )
            for run in data
        ],
        pagination={
            "next_cursor": next_cursor,
            "has_more": has_more,
            "limit": limit,
        },
    )


@router.get("/{id}/versions", response_model=ArtifactVersionsResponse)
async def list_artifact_versions(
    project: Project = Depends(require_project_permission(Permission.VERSION_READ)),
    session: AsyncSession = Depends(get_db),
    artifact_type: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> ArtifactVersionsResponse:
    """List artifact versions (SDK, client, etc.)."""
    stmt = (
        select(ArtifactVersion)
        .where(ArtifactVersion.project_id == project.id)
        .order_by(ArtifactVersion.version_number.desc())
    )

    if artifact_type is not None:
        stmt = stmt.where(ArtifactVersion.artifact_type == artifact_type)

    if cursor:
        try:
            cursor_version = int(cursor)
            stmt = stmt.where(ArtifactVersion.version_number < cursor_version)
        except ValueError:
            pass

    stmt = stmt.limit(limit + 1)
    rows = list((await session.execute(stmt)).scalars())

    has_more = len(rows) > limit
    data = rows[:limit]

    next_cursor = None
    if has_more and data:
        next_cursor = str(data[-1].version_number)

    return ArtifactVersionsResponse(
        data=[
            ArtifactVersionResponse(
                id=version.id,
                artifact_type=version.artifact_type,
                version_number=version.version_number,
                diff_ref=version.diff_ref,
                created_at=version.created_at,
            )
            for version in data
        ],
        pagination={
            "next_cursor": next_cursor,
            "has_more": has_more,
            "limit": limit,
        },
    )


@router.post(
    "/{id}/versions/{version_id}/rollback",
    response_model=RollbackResponse,
    status_code=status.HTTP_201_CREATED,
)
async def rollback_artifact_version(
    version_id: uuid.UUID,
    project: Project = Depends(require_project_permission(Permission.VERSION_ROLLBACK)),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> RollbackResponse:
    """Rollback to a previous artifact version."""
    target_version = await session.get(ArtifactVersion, version_id)
    if target_version is None or target_version.project_id != project.id:
        raise NotFoundError("Artifact version not found.")

    latest_version = await session.scalar(
        select(ArtifactVersion)
        .where(ArtifactVersion.project_id == project.id)
        .where(ArtifactVersion.artifact_type == target_version.artifact_type)
        .order_by(ArtifactVersion.version_number.desc())
        .limit(1)
    )

    if latest_version is None:
        raise UnprocessableEntityError("No versions exist to rollback from.")

    new_version_number = (latest_version.version_number + 1) if latest_version else 1

    new_version = ArtifactVersion(
        project_id=project.id,
        artifact_type=target_version.artifact_type,
        version_number=new_version_number,
        diff_ref=target_version.diff_ref,
    )
    session.add(new_version)
    await session.flush()

    await audit_service.record(
        session,
        action="version.rolled_back",
        actor_type=ActorType.USER,
        organization_id=project.organization_id,
        actor_user_id=principal.user_id,
        resource_type="artifact_version",
        resource_id=str(new_version.id),
        metadata={
            "rolled_back_from": str(latest_version.id) if latest_version else None,
            "rolled_back_to": str(target_version.id),
            "artifact_type": target_version.artifact_type,
        },
    )

    return RollbackResponse(
        version_id=new_version.id,
        rolled_back_from=latest_version.id if latest_version else target_version.id,
        status="rolled_back",
        created_at=new_version.created_at,
    )
