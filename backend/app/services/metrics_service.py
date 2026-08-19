"""Monitoring metrics service for aggregating usage and performance data."""

from __future__ import annotations

import datetime
import decimal
import uuid
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.testing import TestResult, TestRun
from app.models.workflow import WorkflowRun

MetricsPeriod = Literal["7d", "30d", "90d"]


def _period_to_days(period: MetricsPeriod) -> int:
    return {"7d": 7, "30d": 30, "90d": 90}[period]


def _period_start(period: MetricsPeriod) -> datetime.datetime:
    days = _period_to_days(period)
    return datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)


async def get_project_metrics(
    session: AsyncSession,
    project_id: uuid.UUID,
    period: MetricsPeriod,
) -> dict[str, float | int | decimal.Decimal]:
    """Aggregate metrics for a single project."""
    start_date = _period_start(period)

    workflow_stats = await session.execute(
        select(
            func.count().label("total"),
            func.sum(
                func.case((WorkflowRun.status == "completed", 1), else_=0)
            ).label("completed"),
            func.avg(
                func.extract("epoch", WorkflowRun.completed_at)
                - func.extract("epoch", WorkflowRun.started_at)
            ).label("avg_duration_seconds"),
            func.sum(WorkflowRun.total_tokens_used).label("total_tokens"),
            func.sum(WorkflowRun.estimated_cost_usd).label("total_cost"),
        )
        .where(WorkflowRun.project_id == project_id)
        .where(WorkflowRun.started_at >= start_date)
    )
    ws = workflow_stats.first()

    total_workflows = int(ws.total) if ws and ws.total else 0
    completed_workflows = int(ws.completed) if ws and ws.completed else 0
    workflow_success_rate = (completed_workflows / total_workflows) if total_workflows > 0 else 0.0
    avg_duration_seconds = float(ws.avg_duration_seconds) if ws and ws.avg_duration_seconds else 0.0
    avg_time_to_integration_minutes = avg_duration_seconds / 60.0
    total_tokens = int(ws.total_tokens) if ws and ws.total_tokens else 0
    total_cost = decimal.Decimal(str(ws.total_cost)) if ws and ws.total_cost else decimal.Decimal("0")  # noqa: E501

    test_stats = await session.execute(
        select(
            func.count().label("total"),
            func.sum(func.case((TestResult.status == "passed", 1), else_=0)).label("passed"),
        )
        .select_from(TestResult)
        .join(TestRun)
        .where(TestRun.project_id == project_id)
        .where(TestRun.created_at >= start_date)
    )
    ts = test_stats.first()

    total_tests = int(ts.total) if ts and ts.total else 0
    passed_tests = int(ts.passed) if ts and ts.passed else 0
    test_pass_rate = (passed_tests / total_tests) if total_tests > 0 else 0.0

    return {
        "workflow_success_rate": round(workflow_success_rate, 4),
        "avg_time_to_integration_minutes": round(avg_time_to_integration_minutes, 2),
        "test_pass_rate": round(test_pass_rate, 4),
        "total_token_spend": total_tokens,
        "estimated_cost_usd": total_cost,
    }


async def get_org_metrics(
    session: AsyncSession,
    organization_id: uuid.UUID,
    period: MetricsPeriod,
) -> dict[str, float | int | decimal.Decimal]:
    """Aggregate metrics for an organization."""
    start_date = _period_start(period)

    project_ids_stmt = select(Project.id).where(Project.organization_id == organization_id)
    project_ids = list((await session.execute(project_ids_stmt)).scalars())

    workflow_stats = await session.execute(
        select(
            func.count().label("total"),
            func.avg(
                func.extract("epoch", WorkflowRun.completed_at)
                - func.extract("epoch", WorkflowRun.started_at)
            ).label("avg_duration_seconds"),
        )
        .where(WorkflowRun.project_id.in_(project_ids))
        .where(WorkflowRun.started_at >= start_date)
    )
    ws = workflow_stats.first()

    total_workflows = int(ws.total) if ws and ws.total else 0
    avg_duration_seconds = float(ws.avg_duration_seconds) if ws and ws.avg_duration_seconds else 0.0
    avg_time_to_integration_minutes = avg_duration_seconds / 60.0

    test_stats = await session.execute(
        select(
            func.count().label("total"),
            func.sum(func.case((TestResult.status == "passed", 1), else_=0)).label("passed"),
        )
        .select_from(TestResult)
        .join(TestRun)
        .where(TestRun.project_id.in_(project_ids))
        .where(TestRun.created_at >= start_date)
    )
    ts = test_stats.first()

    total_tests = int(ts.total) if ts and ts.total else 0
    passed_tests = int(ts.passed) if ts and ts.passed else 0
    test_pass_rate = (passed_tests / total_tests) if total_tests > 0 else 0.0

    active_projects = await session.scalar(
        select(func.count())
        .select_from(Project)
        .where(Project.organization_id == organization_id)
        .where(Project.archived_at.is_(None))
    ) or 0

    total_cost = await session.scalar(
        select(func.sum(WorkflowRun.estimated_cost_usd))
        .where(WorkflowRun.project_id.in_(project_ids))
        .where(WorkflowRun.started_at >= start_date)
    ) or decimal.Decimal("0")

    return {
        "avg_time_to_integration_minutes": round(avg_time_to_integration_minutes, 2),
        "test_pass_rate": round(test_pass_rate, 4),
        "monthly_token_spend_usd": total_cost,
        "active_projects": int(active_projects),
        "total_workflows": total_workflows,
    }
