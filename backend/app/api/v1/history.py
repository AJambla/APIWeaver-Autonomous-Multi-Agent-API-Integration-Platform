"""History & Versioning API routes (`API.md §6.9`)."""

from __future__ import annotations

import datetime
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_principal, get_db
from app.core.errors import ConflictError, NotFoundError
from app.models.enums import ActorType
from app.models.project import Project
from app.models.versioning import ArtifactVersion
from app.models.workflow import WorkflowRun
from app.rbac.enforce import require_project_permission
from app.rbac.policy import Permission, Principal
from app.schemas.common import Page, PaginationMeta, decode_cursor, encode_cursor
from app.schemas.history import (
    HistoryItemResponse,
    HistoryResponse,
    VersionResponse,
    VersionRollbackRequest,
    VersionRollbackResponse,
)
from app.services import audit_service

router = APIRouter(tags=["history"])


@router.get("/projects/{id}/history", response_model=HistoryResponse)
async def get_project_history(
    project: Project = Depends(require_project_permission(Permission.WORKFLOW_READ)),
    session: AsyncSession = Depends(get_db),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> HistoryResponse:
    """Paginated workflow run timeline for a project."""
    stmt = select(WorkflowRun).where(WorkflowRun.project_id == project.id)

    if cursor and (position := decode_cursor(cursor)):
        try:
            last_created = datetime.datetime.fromisoformat(position["created_at"])
            last_id = uuid.UUID(position["id"])
            stmt = stmt.where(
                tuple_(WorkflowRun.started_at, WorkflowRun.id) < tuple_(last_created, last_id)
            )
        except (KeyError, TypeError, ValueError):
            pass

    stmt = stmt.order_by(WorkflowRun.started_at.desc(), WorkflowRun.id.desc()).limit(limit + 1)

    rows = list((await session.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    page_rows = rows[:limit]

    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor({"created_at": last.started_at.isoformat(), "id": str(last.id)})

    items = [
        HistoryItemResponse(
            id=row.id,
            workflow_run_id=row.id,
            status=row.status,
            stages=[],  # Would need to fetch from checkpoints or state
            started_at=row.started_at or row.created_at,
            completed_at=row.completed_at,
            total_tokens=row.total_tokens_used,
        )
        for row in page_rows
    ]

    return HistoryResponse(
        data=items,
        pagination=PaginationMeta(next_cursor=next_cursor, has_more=has_more, limit=limit),
    )


@router.get("/projects/{id}/versions", response_model=Page[VersionResponse])
async def get_project_versions(
    project: Project = Depends(require_project_permission(Permission.CODE_READ)),
    session: AsyncSession = Depends(get_db),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> Page[VersionResponse]:
    """List artifact versions for a project."""
    stmt = select(ArtifactVersion).where(ArtifactVersion.project_id == project.id)

    if cursor and (position := decode_cursor(cursor)):
        try:
            last_created = datetime.datetime.fromisoformat(position["created_at"])
            last_id = uuid.UUID(position["id"])
            stmt = stmt.where(
                tuple_(ArtifactVersion.created_at, ArtifactVersion.id)
                < tuple_(last_created, last_id)
            )
        except (KeyError, TypeError, ValueError):
            pass

    stmt = stmt.order_by(
        ArtifactVersion.created_at.desc(), ArtifactVersion.id.desc()
    ).limit(limit + 1)

    rows = list((await session.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    page_rows = rows[:limit]

    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor({"created_at": last.created_at.isoformat(), "id": str(last.id)})

    items = [
        VersionResponse(
            id=row.id,
            artifact_type=row.artifact_type,
            version_number=row.version_number,
            created_at=row.created_at,
            diff_ref=row.diff_ref,
            is_active=getattr(row, "is_active", False),
        )
        for row in page_rows
    ]

    return Page[VersionResponse](
        data=items,
        pagination=PaginationMeta(next_cursor=next_cursor, has_more=has_more, limit=limit),
    )


@router.post(
    "/projects/{id}/versions/{version_id}/rollback",
    response_model=VersionRollbackResponse,
    status_code=status.HTTP_200_OK,
)
async def rollback_version(
    version_id: uuid.UUID,
    payload: VersionRollbackRequest,
    project: Project = Depends(require_project_permission(Permission.EXPORT_CREATE)),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> VersionRollbackResponse:
    """Rollback to a previous artifact version (sets is_active=true)."""
    if not payload.confirm:
        raise ConflictError("Rollback requires confirmation.")

    version = await session.get(ArtifactVersion, version_id)
    if version is None:
        raise NotFoundError("Version not found.")
    if version.project_id != project.id:
        raise NotFoundError("Version not found in this project.")

    # Deactivate all other versions of same type
    await session.execute(
        select(ArtifactVersion)
        .where(
            ArtifactVersion.project_id == project.id,
            ArtifactVersion.artifact_type == version.artifact_type,
            ArtifactVersion.id != version.id,
            ArtifactVersion.is_active == True,  # noqa: E712
        )
    )
    # SQLAlchemy 2.0 style update
    from sqlalchemy import update
    await session.execute(
        update(ArtifactVersion)
        .where(
            ArtifactVersion.project_id == project.id,
            ArtifactVersion.artifact_type == version.artifact_type,
            ArtifactVersion.id != version.id,
        )
        .values(is_active=False)
    )

    # Activate target version
    version.is_active = True
    await session.flush()

    await audit_service.record(
        session,
        action="artifact.rollback",
        actor_type=ActorType.USER,
        organization_id=project.organization_id,
        actor_user_id=principal.user_id,
        resource_type="artifact_version",
        resource_id=str(version.id),
        metadata={"artifact_type": version.artifact_type, "version_number": version.version_number},
    )

    return VersionRollbackResponse(
        id=version.id,
        artifact_type=version.artifact_type,
        version_number=version.version_number,
        is_active=True,
        message=f"Rolled back {version.artifact_type} to version {version.version_number}",
    )