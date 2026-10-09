"""Regression tests for API correctness bugs fixed in the hardening pass."""

from __future__ import annotations

import datetime
import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import create_access_token
from app.models.enums import OrgRole, WorkflowStatus
from app.models.export import Export
from app.models.workflow import AgentEvent, WorkflowRun
from tests.conftest import add_org_member, make_org, make_project, make_user


async def _owner_project(session_factory: async_sessionmaker[AsyncSession], settings: Settings):
    async with session_factory() as session:
        user = await make_user(session, email=f"reg-{uuid.uuid4().hex[:8]}@example.com")
        org = await make_org(session, name=f"Reg {uuid.uuid4().hex[:6]}")
        await add_org_member(session, org=org, user=user, role=OrgRole.OWNER)
        project = await make_project(session, org=org)
        await session.commit()
    token = create_access_token(user_id=user.id, org_id=org.id, role=OrgRole.OWNER, settings=settings)
    return project, {"Authorization": f"Bearer {token.token}"}


async def test_log_pagination_reaches_the_second_page(
    client: AsyncClient, session_factory, test_settings
) -> None:
    project, headers = await _owner_project(session_factory, test_settings)
    base = datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC)
    async with session_factory() as session:
        run = WorkflowRun(project_id=project.id, status=WorkflowStatus.COMPLETED)
        other = WorkflowRun(project_id=project.id, status=WorkflowStatus.COMPLETED)
        session.add_all([run, other])
        await session.flush()
        for i in range(5):
            session.add(
                AgentEvent(
                    workflow_run_id=run.id,
                    agent_name="a",
                    event_type=f"e{i}",
                    created_at=base + datetime.timedelta(seconds=i),
                )
            )
        session.add(AgentEvent(workflow_run_id=other.id, agent_name="b", event_type="other", created_at=base))
        await session.commit()

    first = await client.get(f"/api/v1/projects/{project.id}/logs?limit=2&run_id={run.id}", headers=headers)
    assert first.status_code == 200, first.text
    cursor = first.json()["pagination"]["next_cursor"]
    assert cursor
    second = await client.get(
        f"/api/v1/projects/{project.id}/logs?limit=2&run_id={run.id}&cursor={cursor}", headers=headers
    )
    assert second.status_code == 200, second.text
    seen = [e["event_type"] for e in first.json()["data"] + second.json()["data"]]
    assert seen == ["e4", "e3", "e2", "e1"]
    assert "other" not in seen


async def test_history_pages_through_queued_runs(
    client: AsyncClient, session_factory, test_settings
) -> None:
    project, headers = await _owner_project(session_factory, test_settings)
    async with session_factory() as session:
        for _ in range(3):
            session.add(WorkflowRun(project_id=project.id, status=WorkflowStatus.QUEUED))
        await session.commit()

    first = await client.get(f"/api/v1/projects/{project.id}/history?limit=2", headers=headers)
    assert first.status_code == 200, first.text
    cursor = first.json()["pagination"]["next_cursor"]
    assert cursor
    second = await client.get(
        f"/api/v1/projects/{project.id}/history?limit=2&cursor={cursor}", headers=headers
    )
    assert second.status_code == 200, second.text
    ids = {r["id"] for r in first.json()["data"] + second.json()["data"]}
    assert len(ids) == 3


async def test_downloads_never_serve_another_export_types_artifact(
    client: AsyncClient, session_factory, test_settings
) -> None:
    from app.services.storage_service import storage_service

    project, headers = await _owner_project(session_factory, test_settings)
    await storage_service.upload(f"exports/{project.id}/mcp/manifest.json", b'{"mcp": true}')
    async with session_factory() as session:
        export = Export(project_id=project.id, export_type="docker", status="completed")
        session.add(export)
        await session.commit()

    res = await client.get(
        f"/api/v1/projects/{project.id}/exports/{export.id}/download", headers=headers
    )

    assert res.status_code == 404, res.text


async def test_export_list_limit_is_bounded(
    client: AsyncClient, session_factory, test_settings
) -> None:
    project, headers = await _owner_project(session_factory, test_settings)
    res = await client.get(f"/api/v1/projects/{project.id}/exports?limit=100000", headers=headers)
    assert res.status_code == 400, res.text
