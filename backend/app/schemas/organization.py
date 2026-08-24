"""Organization schemas — `API.md §3`, `API.md §6.1`."""

from __future__ import annotations

from pydantic import Field

from app.schemas.common import ResponseModel, StrictModel


class RateLimitUpdate(StrictModel):
    """`PUT /organizations/{id}/rate-limit` request body."""

    limit: int = Field(ge=60, description="Custom rate limit requests per minute (min 60)")


class RateLimitResponse(ResponseModel):
    """Rate limit configuration response."""

    limit: int
    is_override: bool
    plan_tier: str