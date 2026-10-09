"""Organization routes — `API.md §3`."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.deps import get_db
from app.core.errors import ForbiddenError, NotFoundError, UnprocessableEntityError
from app.core.ratelimit import TIER_REQUESTS_PER_MINUTE
from app.models.enums import PlanTier
from app.models.organization import Organization
from app.rbac.enforce import require_org_permission
from app.rbac.policy import Permission, Principal
from app.schemas.organization import RateLimitResponse, RateLimitUpdate

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _tier_limit(plan_tier: str | None) -> int:
    return TIER_REQUESTS_PER_MINUTE.get(plan_tier or "", TIER_REQUESTS_PER_MINUTE["free"])


async def _load_org(session: AsyncSession, org_id: uuid.UUID) -> Organization:
    # `require_org_permission` has already proven membership of `org_id`; the dependency
    # returns the caller's `Principal`, not the organization, so the row is loaded here.
    org = await session.get(Organization, org_id)
    if org is None:
        raise NotFoundError()
    return org


@router.put(
    "/{org_id}/rate-limit",
    response_model=RateLimitResponse,
    summary="Set organization rate limit override (Enterprise only)",
)
async def set_rate_limit_override(
    org_id: Annotated[uuid.UUID, Path()],
    payload: RateLimitUpdate,
    _principal: Principal = Depends(require_org_permission(Permission.ORG_EDIT_BILLING)),
    session: AsyncSession = Depends(get_db),
) -> RateLimitResponse:
    """Set a custom rate limit for an Enterprise organization.

    Only organization owners can set this (`ORG_EDIT_BILLING`). The override replaces
    the tier default until removed.
    """
    org = await _load_org(session, org_id)
    if org.plan_tier != PlanTier.ENTERPRISE:
        raise ForbiddenError("Rate limit overrides are only available for Enterprise tier")
    ceiling = get_settings().rate_limit_override_max_rpm
    if payload.limit > ceiling:
        raise UnprocessableEntityError(
            f"Rate limit overrides are capped at {ceiling} requests per minute."
        )

    org.rate_limit_override = payload.limit
    await session.flush()

    return RateLimitResponse(
        limit=org.rate_limit_override or _tier_limit(org.plan_tier),
        is_override=org.rate_limit_override is not None,
        plan_tier=org.plan_tier,
    )


@router.delete(
    "/{org_id}/rate-limit",
    response_model=RateLimitResponse,
    summary="Remove organization rate limit override",
)
async def remove_rate_limit_override(
    org_id: Annotated[uuid.UUID, Path()],
    _principal: Principal = Depends(require_org_permission(Permission.ORG_EDIT_BILLING)),
    session: AsyncSession = Depends(get_db),
) -> RateLimitResponse:
    """Remove the custom rate limit override, reverting to the tier default."""
    org = await _load_org(session, org_id)
    org.rate_limit_override = None
    await session.flush()

    return RateLimitResponse(
        limit=_tier_limit(org.plan_tier),
        is_override=False,
        plan_tier=org.plan_tier,
    )
