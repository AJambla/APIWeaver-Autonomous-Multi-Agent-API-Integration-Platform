"""Tests for Monitoring routes (`API.md §6.10`)."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from httpx import AsyncClient

from app.models.enums import PlanTier, WorkflowStatus
from app.models.export import Export
from app.models.metrics import UsageMetric
from app.models.project import Project
from app.models.testing import TestRun
from app.models.workflow import WorkflowRun
from tests.conftest import TEST_PASSWORD


async def _setup_org_with_data(client: AsyncClient) -> tuple[str, str, dict[str, str]]:
    """Create a user, org, project, and some test data."""
    res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "metrics_user@example.com",
            "password": TEST_PASSWORD,
            "full_name": "Metrics Tester",
            "organization_name": "Metrics Org",
        },
    )
    assert res.status_code == 201
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    me = await client.get("/api/v1/auth/me", headers=headers)
    org_id = me.json()["organizations"][0]["organization_id"]

    proj = await client.post(
        "/api/v1/projects",
        json={"name": "Metrics Test Project", "organization_id": org_id},
        headers=headers,
    )
    assert proj.status_code == 201
    project_id = proj.json()["id"]

    return project_id, org_id, headers


async def test_get_project_metrics(client: AsyncClient, db) -> None:
    project_id, _, headers = await _setup_org_with_data(client)

    async with db as session:
        # Create workflow runs
        for i in range(5):
            run = WorkflowRun(
                project_id=uuid.UUID(project_id),
                status=WorkflowStatus.COMPLETED if i < 3 else WorkflowStatus.FAILED,
                total_tokens_used=500,
                estimated_cost_usd=Decimal("0.05"),
                started_at=datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=2),
                completed_at=datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=2) + datetime.timedelta(minutes=10),
            )
            session.add(run)
        await session.commit()

        # Create test runs
        for i in range(3):
            test_run = TestRun(
                project_id=uuid.UUID(project_id),
                status="completed",
                environment="sandbox",
                summary={"passed": 8, "failed": 2, "skipped": 0, "total": 10},
            )
            session.add(test_run)
        await session.commit()

        # Create exports
        for i in range(2):
            export = Export(
                project_id=uuid.UUID(project_id),
                export_type="sdk",
                status="completed",
            )
            session.add(export)
        await session.commit()

        # Create usage metrics
        for i in range(3):
            metric = UsageMetric(
                organization_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),  # Will be replaced
                metric_name="token_cost_usd",
                value=Decimal("0.10"),
                recorded_at=datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=i),
            )
            session.add(metric)
        await session.commit()

    # Fetch metrics
    res = await client.get(f"/api/v1/projects/{project_id}/metrics", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total_workflow_runs"] == 5
    assert data["successful_exports"] == 2
    assert data["test_pass_rate"] == 0.8  # 24 passed / 30 total
    assert data["avg_time_to_integration_minutes"] is not None
    assert data["monthly_token_spend_usd"] is not None


async def test_get_org_metrics(client: AsyncClient, db) -> None:
    project_id, org_id, headers = await _setup_org_with_data(client)

    async with db as session:
        # Update org plan tier
        from app.models.organization import Organization
        org = await session.get(Organization, uuid.UUID(org_id))
        org.plan_tier = PlanTier.PRO
        await session.commit()

        # Create another project
        proj2 = Project(organization_id=uuid.UUID(org_id), name="Project 2")
        session.add(proj2)
        await session.flush()

        # Create workflow runs across both projects
        for proj in [uuid.UUID(project_id), proj2.id]:
            for i in range(3):
                run = WorkflowRun(
                    project_id=proj,
                    status=WorkflowStatus.COMPLETED,
                    total_tokens_used=200,
                )
                session.add(run)
        await session.commit()

        # Create test runs
        for proj in [uuid.UUID(project_id), proj2.id]:
            test_run = TestRun(
                project_id=proj,
                status="completed",
                environment="sandbox",
                summary={"passed": 5, "failed": 1, "skipped": 0, "total": 6},
            )
            session.add(test_run)
        await session.commit()

        # Create usage metrics
        metric = UsageMetric(
            organization_id=uuid.UUID(org_id),
            metric_name="token_cost_usd",
            value=Decimal("1.50"),
            recorded_at=datetime.datetime.now(datetime.UTC),
        )
        session.add(metric)
        await session.commit()

    # Fetch org metrics
    res = await client.get(f"/api/v1/org/{org_id}/metrics", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["projects_count"] == 2
    assert data["total_workflow_runs"] == 6
    assert data["avg_test_pass_rate"] == 5/6  # 10 passed / 12 total
    assert data["monthly_token_spend_usd"] == 1.5
    assert data["tier_limit_workflow_triggers_hour"] == 100  # Pro tier