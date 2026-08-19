"""Monitoring metrics API contracts (`API.md §6.10`)."""

from __future__ import annotations

import decimal
from typing import Literal

from pydantic import Field

from app.schemas.common import ResponseModel


class ProjectMetricsResponse(ResponseModel):
    """Project-level metrics aggregation."""
    workflow_success_rate: float = Field(
        description="Fraction of successful workflow runs"
    )
    avg_time_to_integration_minutes: float = Field(
        description="Average time from trigger to completion"
    )
    test_pass_rate: float = Field(description="Fraction of passing tests")
    total_token_spend: int = Field(description="Total tokens consumed")
    estimated_cost_usd: decimal.Decimal = Field(description="Estimated cost in USD")


class OrgMetricsResponse(ResponseModel):
    """Organization-level metrics aggregation."""
    avg_time_to_integration_minutes: float = Field(
        description="Average time from trigger to completion"
    )
    test_pass_rate: float = Field(description="Fraction of passing tests")
    monthly_token_spend_usd: decimal.Decimal = Field(
        description="Monthly token spend in USD"
    )
    active_projects: int = Field(description="Number of active projects")
    total_workflows: int = Field(description="Total workflow runs in period")


MetricsPeriod = Literal["7d", "30d", "90d"]
