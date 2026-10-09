"""Organization schemas — `API.md §3`, `API.md §6.1`."""

from __future__ import annotations

from pydantic import Field

from app.schemas.common import ResponseModel, StrictModel


class RateLimitUpdate(StrictModel):
    """`PUT /organizations/{id}/rate-limit` request body."""

    limit: int = Field(
        ge=60,
        le=1_000_000,
        description="Custom requests per minute (min 60; capped by RATE_LIMIT_OVERRIDE_MAX_RPM)",
    )


class RateLimitResponse(ResponseModel):
    """Rate limit configuration response."""

    limit: int
    is_override: bool
    plan_tier: str