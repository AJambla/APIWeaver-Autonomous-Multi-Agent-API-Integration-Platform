"""Retry policy schemas — `Feature.md §15`."""

from __future__ import annotations

from pydantic import Field

from app.schemas.common import ResponseModel, StrictModel


class RetryPolicyRequest(StrictModel):
    """Retry policy configuration request."""

    max_attempts: int = Field(default=3, ge=1, le=10, description="Maximum retry attempts")
    backoff_base_seconds: int = Field(
        default=2, ge=1, le=60, description="Exponential backoff base in seconds"
    )
    retryable_status_codes: list[int] = Field(
        default=[429, 500, 502, 503, 504],
        description="HTTP status codes that should trigger a retry",
    )


class RetryPolicyResponse(ResponseModel):
    """Retry policy configuration response."""

    max_attempts: int
    backoff_base_seconds: int
    retryable_status_codes: list[int]