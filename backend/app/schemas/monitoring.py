"""Monitoring API contracts (`API.md §6.10`)."""

from __future__ import annotations

from app.schemas.common import ResponseModel


class ProjectMetricsResponse(ResponseModel):
    avg_time_to_integration_minutes: float | None = None
    test_pass_rate: float | None = None
    monthly_token_spend_usd: float | None = None
    total_workflow_runs: int = 0
    successful_exports: int = 0


class OrgMetricsResponse(ResponseModel):
    projects_count: int = 0
    total_workflow_runs: int = 0
    avg_test_pass_rate: float | None = None
    monthly_token_spend_usd: float = 0.0
    tier_limit_workflow_triggers_hour: int = 0