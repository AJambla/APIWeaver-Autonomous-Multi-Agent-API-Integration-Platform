"""Organization routes — `API.md §3`."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.errors import ForbiddenError
from app.core.ratelimit import TIER_REQUESTS_PER_MINUTE
from app.models.enums import PlanTier
from app.models.organization import Organization
from app.rbac.enforce import require_org_permission
from app.rbac.policy import Permission
from app.schemas.organization import RateLimitResponse, RateLimitUpdate

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.put(
    "/{org_id}/rate-limit",
    response_model=RateLimitResponse,
    summary="Set organization rate limit override (Enterprise only)",
)
async def set_rate_limit_override(
    payload: RateLimitUpdate,
    org: Organization = Depends(require_org_permission(Permission.ORG_EDIT_BILLING)),
    session: AsyncSession = Depends(get_db),
) -> RateLimitResponse:
    """Set a custom rate limit for an Enterprise organization.

    Only organization owners can set this (`ORG_EDIT_BILLING`). The override replaces
    the tier default until removed.
    """
    if org.plan_tier != PlanTier.ENTERPRISE:
        raise ForbiddenError("Rate limit overrides are only available for Enterprise tier")

    org.rate_limit_override = payload.limit
    await session.flush()

    return RateLimitResponse(
        limit=org.rate_limit_override,
        is_override=org.rate_limit_override is not None,
        plan_tier=org.plan_tier,
    )


@router.delete(
    "/{org_id}/rate-limit",
    response_model=RateLimitResponse,
    summary="Remove organization rate limit override",
)
async def remove_rate_limit_override(
    org: Organization = Depends(require_org_permission(Permission.ORG_EDIT_BILLING)),
    session: AsyncSession = Depends(get_db),
) -> RateLimitResponse:
    """Remove the custom rate limit override, reverting to the tier default."""
    org.rate_limit_override = None
    await session.flush()

    plan_tier = org.plan_tier
    if plan_tier == PlanTier.ENTERPRISE:
        effective = TIER_REQUESTS_PER_MINUTE["enterprise"]
    else:
        effective = TIER_REQUESTS_PER_MINUTE.get(plan_tier, TIER_REQUESTS_PER_MINUTE["free"])

    return RateLimitResponse(
        limit=effective,
        is_override=False,
        plan_tier=plan_tier,
    )