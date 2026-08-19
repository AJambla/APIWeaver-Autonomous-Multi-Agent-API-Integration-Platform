"""Monitoring metrics API routes (`API.md §6.10`)."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.models.project import Project
from app.rbac.enforce import require_org_permission, require_project_permission
from app.rbac.policy import Permission, Principal
from app.schemas.metrics import OrgMetricsResponse, ProjectMetricsResponse
from app.services.metrics_service import get_org_metrics, get_project_metrics

router = APIRouter(tags=["metrics"])

MetricsPeriod = Literal["7d", "30d", "90d"]


@router.get(
    "/projects/{id}/metrics",
    response_model=ProjectMetricsResponse,
)
async def get_project_metrics_endpoint(
    project: Project = Depends(require_project_permission(Permission.PROJECT_METRICS_READ)),
    session: AsyncSession = Depends(get_db),
    period: MetricsPeriod = Query(default="30d"),
) -> ProjectMetricsResponse:
    """Project-level metrics aggregation."""
    metrics = await get_project_metrics(session, project.id, period)
    return ProjectMetricsResponse(**metrics)


@router.get(
    "/org/{org_id}/metrics",
    response_model=OrgMetricsResponse,
)
async def get_org_metrics_endpoint(
    org_id: uuid.UUID,
    principal: Principal = Depends(require_org_permission(Permission.ORG_METRICS_READ)),
    session: AsyncSession = Depends(get_db),
    period: MetricsPeriod = Query(default="30d"),
) -> OrgMetricsResponse:
    """Organization-level metrics aggregation."""
    metrics = await get_org_metrics(session, org_id, period)
    return OrgMetricsResponse(**metrics)
