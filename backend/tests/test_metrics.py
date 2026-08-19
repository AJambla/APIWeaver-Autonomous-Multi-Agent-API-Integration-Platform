"""Tests for metrics routes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token
from app.models.enums import OrgRole, ProjectRole, WorkflowStatus
from app.models.workflow import WorkflowRun
from tests.conftest import (
    add_org_member,
    add_project_member,
    make_org,
    make_project,
    make_user,
)


@pytest.fixture
async def setup_data(db):
    org = await make_org(db, name="Metrics Org")
    user = await make_user(db, email="metrics@example.com", name="Metrics User")
    await add_org_member(db, org=org, user=user, role=OrgRole.MEMBER)
    project = await make_project(db, org=org, name="Metrics Project")
    await add_project_member(db, project=project, user=user, role=ProjectRole.VIEWER)
    return org, user, project


@pytest.mark.asyncio
async def test_project_metrics_unauthenticated(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/projects/{uuid.uuid4()}/metrics")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_project_metrics(client: AsyncClient, db, test_settings, setup_data) -> None:
    org, user, project = setup_data

    run = WorkflowRun(
        project_id=project.id,
        triggered_by=user.id,
        status=WorkflowStatus.COMPLETED,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        total_tokens_used=1000,
        estimated_cost_usd=0.05,
    )
    db.add(run)
    await db.commit()

    token = create_access_token(
        user_id=user.id,
        org_id=org.id,
        role=OrgRole.MEMBER,
        settings=test_settings,
    )
    headers = {"Authorization": f"Bearer {token.token}"}

    response = await client.get(
        f"/api/v1/projects/{project.id}/metrics",
        headers=headers,
        params={"period": "30d"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "workflow_success_rate" in data
    assert "avg_time_to_integration_minutes" in data
    assert "test_pass_rate" in data
    assert "total_token_spend" in data
    assert "estimated_cost_usd" in data


@pytest.mark.asyncio
async def test_org_metrics_unauthenticated(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/org/{uuid.uuid4()}/metrics")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_org_metrics(client: AsyncClient, db, test_settings, setup_data) -> None:
    org, user, project = setup_data

    token = create_access_token(
        user_id=user.id,
        org_id=org.id,
        role=OrgRole.MEMBER,
        settings=test_settings,
    )
    headers = {"Authorization": f"Bearer {token.token}"}

    response = await client.get(
        f"/api/v1/org/{org.id}/metrics",
        headers=headers,
        params={"period": "7d"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "avg_time_to_integration_minutes" in data
    assert "test_pass_rate" in data
    assert "monthly_token_spend_usd" in data
    assert "active_projects" in data
    assert "total_workflows" in data
