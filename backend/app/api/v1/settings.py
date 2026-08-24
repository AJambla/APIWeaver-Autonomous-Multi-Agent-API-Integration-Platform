"""Project settings routes — `Feature.md §15`."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.models.project import Project
from app.models.retry import RetryConfig
from app.rbac.enforce import require_project_permission
from app.rbac.policy import Permission
from app.schemas.retry import RetryPolicyRequest, RetryPolicyResponse

router = APIRouter(prefix="/projects/{id}/settings", tags=["project-settings"])


# Default retry policy values matching model defaults
DEFAULT_RETRY_POLICY = RetryPolicyResponse(
    max_attempts=3,
    backoff_base_seconds=2,
    retryable_status_codes=[429, 500, 502, 503, 504],
)


@router.get(
    "/retry-policy",
    response_model=RetryPolicyResponse,
    summary="Get project retry policy",
)
async def get_retry_policy(
    project: Project = Depends(require_project_permission(Permission.PROJECT_SETTINGS_READ)),
    session: AsyncSession = Depends(get_db),
) -> RetryPolicyResponse:
    """Get the retry policy for a project. Returns defaults if not configured."""
    retry_config = await session.scalar(
        select(RetryConfig).where(RetryConfig.project_id == project.id)
    )

    if retry_config is None:
        return DEFAULT_RETRY_POLICY

    return RetryPolicyResponse(
        max_attempts=retry_config.max_attempts,
        backoff_base_seconds=retry_config.backoff_base_seconds,
        retryable_status_codes=retry_config.retryable_status_codes,
    )


@router.put(
    "/retry-policy",
    response_model=RetryPolicyResponse,
    summary="Update project retry policy",
)
async def update_retry_policy(
    payload: RetryPolicyRequest,
    project: Project = Depends(require_project_permission(Permission.PROJECT_SETTINGS_WRITE)),
    session: AsyncSession = Depends(get_db),
) -> RetryPolicyResponse:
    """Update (upsert) the retry policy for a project."""
    retry_config = await session.scalar(
        select(RetryConfig).where(RetryConfig.project_id == project.id)
    )

    if retry_config is None:
        retry_config = RetryConfig(project_id=project.id)
        session.add(retry_config)

    retry_config.max_attempts = payload.max_attempts
    retry_config.backoff_base_seconds = payload.backoff_base_seconds
    retry_config.retryable_status_codes = payload.retryable_status_codes

    await session.flush()

    return RetryPolicyResponse(
        max_attempts=retry_config.max_attempts,
        backoff_base_seconds=retry_config.backoff_base_seconds,
        retryable_status_codes=retry_config.retryable_status_codes,
    )