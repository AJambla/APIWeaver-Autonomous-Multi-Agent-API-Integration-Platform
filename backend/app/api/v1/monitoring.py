"""Monitoring API routes (`API.md §6.10`)."""

from __future__ import annotations

import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.models.export import Export
from app.models.metrics import UsageMetric
from app.models.organization import Organization
from app.models.project import Project
from app.models.testing import TestRun
from app.models.workflow import WorkflowRun
from app.rbac.enforce import require_org_permission, require_project_permission
from app.rbac.policy import Permission
from app.schemas.monitoring import OrgMetricsResponse, ProjectMetricsResponse

router = APIRouter(tags=["monitoring"])


@router.get("/projects/{id}/metrics", response_model=ProjectMetricsResponse)
async def get_project_metrics(
    project: Project = Depends(require_project_permission(Permission.TEST_READ)),
    session: AsyncSession = Depends(get_db),
    days: int = Query(default=30, ge=1, le=365),
) -> ProjectMetricsResponse:
    """Get aggregated metrics for a project."""
    since = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)

    # Total workflow runs
    total_runs = await session.scalar(
        select(func.count(WorkflowRun.id)).where(
            WorkflowRun.project_id == project.id,
            WorkflowRun.created_at >= since,
        )
    ) or 0

    # Successful exports
    successful_exports = await session.scalar(
        select(func.count(Export.id)).where(
            Export.project_id == project.id,
            Export.status == "completed",
            Export.created_at >= since,
        )
    ) or 0

    # Avg time to integration (completed workflows)
    completed_runs = await session.execute(
        select(WorkflowRun.started_at, WorkflowRun.completed_at).where(
            WorkflowRun.project_id == project.id,
            WorkflowRun.status == "completed",
            WorkflowRun.started_at.is_not(None),
            WorkflowRun.completed_at.is_not(None),
            WorkflowRun.created_at >= since,
        )
    )
    durations = [
        (row.completed_at - row.started_at).total_seconds() / 60
        for row in completed_runs.all()
        if row.started_at and row.completed_at
    ]
    avg_time = sum(durations) / len(durations) if durations else None

    # Test pass rate
    test_runs = await session.execute(
        select(TestRun.summary).where(
            TestRun.project_id == project.id,
            TestRun.status == "completed",
            TestRun.created_at >= since,
        )
    )
    total_passed = 0
    total_tests = 0
    for (summary,) in test_runs.all():
        if isinstance(summary, dict):
            total_passed += summary.get("passed", 0)
            total_tests += summary.get("total", 0)
    test_pass_rate = total_passed / total_tests if total_tests > 0 else None

    # Monthly token spend (from usage_metrics)
    monthly_spend = await session.scalar(
        select(func.sum(UsageMetric.value)).where(
            UsageMetric.organization_id == project.organization_id,
            UsageMetric.metric_name == "token_cost_usd",
            UsageMetric.recorded_at >= since,
        )
    ) or Decimal("0")

    return ProjectMetricsResponse(
        avg_time_to_integration_minutes=avg_time,
        test_pass_rate=test_pass_rate,
        monthly_token_spend_usd=float(monthly_spend),
        total_workflow_runs=total_runs,
        successful_exports=successful_exports,
    )


@router.get("/org/{org_id}/metrics", response_model=OrgMetricsResponse)
async def get_org_metrics(
    org: Organization = Depends(require_org_permission(Permission.ORG_VIEW_BILLING)),
    session: AsyncSession = Depends(get_db),
    days: int = Query(default=30, ge=1, le=365),
) -> OrgMetricsResponse:
    """Get aggregated metrics for an organization."""
    since = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)

    # Projects count
    projects_count = await session.scalar(
        select(func.count(Project.id)).where(
            Project.organization_id == org.id,
            Project.archived_at.is_(None),
        )
    ) or 0

    # Total workflow runs across all projects
    total_runs = await session.scalar(
        select(func.count(WorkflowRun.id))
        .join(Project, Project.id == WorkflowRun.project_id)
        .where(
            Project.organization_id == org.id,
            WorkflowRun.created_at >= since,
        )
    ) or 0

    # Avg test pass rate across projects
    test_runs = await session.execute(
        select(TestRun.summary)
        .join(Project, Project.id == TestRun.project_id)
        .where(
            Project.organization_id == org.id,
            TestRun.status == "completed",
            TestRun.created_at >= since,
        )
    )
    total_passed = 0
    total_tests = 0
    for (summary,) in test_runs.all():
        if isinstance(summary, dict):
            total_passed += summary.get("passed", 0)
            total_tests += summary.get("total", 0)
    avg_test_pass_rate = total_passed / total_tests if total_tests > 0 else None

    # Monthly token spend
    monthly_spend = await session.scalar(
        select(func.sum(UsageMetric.value)).where(
            UsageMetric.organization_id == org.id,
            UsageMetric.metric_name == "token_cost_usd",
            UsageMetric.recorded_at >= since,
        )
    ) or Decimal("0")

    # Tier limit
    from app.core.ratelimit import TIER_LIMITS
    tier_limit = TIER_LIMITS.get(org.plan_tier, {}).get("workflow_triggers_hour", 0)

    return OrgMetricsResponse(
        projects_count=projects_count,
        total_workflow_runs=total_runs,
        avg_test_pass_rate=avg_test_pass_rate,
        monthly_token_spend_usd=float(monthly_spend),
        tier_limit_workflow_triggers_hour=tier_limit,
    )