"""Tests for AgentEvent / ToolCall emission (Track A3).

The orchestrator writes structured trace events (plus derived tool calls) so the
project logs and per-run tool-calls APIs return real rows.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ProjectRole
from app.models.spec import APISpec
from app.models.workflow import AgentEvent, ToolCall, WorkflowRun
from app.workflows.event_recorder import record_agent_event
from tests.conftest import (
    TEST_PASSWORD,
    add_org_member,
    add_project_member,
    make_org,
    make_project,
    make_user,
)


async def test_record_agent_event_persists_tool_calls(db: AsyncSession) -> None:
    org = await make_org(db, name="Events Org")
    project = await make_project(db, org=org, name="Events Project")
    run = WorkflowRun(project_id=project.id)
    db.add(run)
    await db.flush()

    event_id = await record_agent_event(
        db,
        workflow_run_id=run.id,
        agent_name="code_agent",
        event_type="stage_completed",
        payload={"node_name": "code_agent_phase_1", "llm_tokens": 120},
        tool_calls=[
            {
                "tool_name": "storage.upload",
                "arguments": {"file_path": "client.py", "language": "python"},
                "result": {"s3_key": "generated/x/1/client.py"},
            },
            {
                "tool_name": "storage.upload",
                "arguments": {"file_path": "models.py", "language": "python"},
                "result": {"s3_key": "generated/x/2/models.py"},
                "duration_ms": 12,
            },
        ],
    )

    event = (await db.scalars(select(AgentEvent))).one()
    assert event_id == event.id
    assert event_id > 0
    calls = list(
        (await db.scalars(select(ToolCall).where(ToolCall.agent_event_id == event_id))).all()
    )
    assert [c.tool_name for c in calls] == ["storage.upload", "storage.upload"]
    assert calls[0].arguments == {"file_path": "client.py", "language": "python"}
    assert calls[1].duration_ms == 12
    assert calls[0].result == {"s3_key": "generated/x/1/client.py"}


from app.workflows.llm import LLMClient


async def test_plan_run_writes_events_visible_in_project_logs(
    client: AsyncClient, db: AsyncSession, monkeypatch
) -> None:
    async def _fake_planner_generate_json(*args, **kwargs):
        return {
            "phases": [{"phase_number": 1, "name": "Users", "endpoints": ["GET /users", "POST /users"]}],
            "dependency_graph": {"nodes": [], "edges": []},
        }, 50

    monkeypatch.setattr(LLMClient, "generate_json", _fake_planner_generate_json)

    res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"events-{uuid.uuid4().hex[:8]}@example.com",
            "password": TEST_PASSWORD,
            "full_name": "Events Tester",
            "organization_name": f"Events Org {uuid.uuid4().hex[:6]}",
        },
    )
    assert res.status_code == 201, res.text
    headers = {"Authorization": f"Bearer {res.json()['access_token']}"}
    me = await client.get("/api/v1/auth/me", headers=headers)
    org_id = me.json()["organizations"][0]["organization_id"]
    proj = await client.post(
        "/api/v1/projects",
        json={"name": "Events Pipeline", "organization_id": org_id},
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    project_id = uuid.UUID(proj.json()["id"])

    db.add(
        APISpec(
            project_id=project_id,
            raw_normalized={
                "format": "openapi",
                "title": "Users API",
                "base_url": "https://api.example.com",
                "endpoints": [
                    {"method": "GET", "path": "/users", "summary": "List users"},
                    {"method": "POST", "path": "/users", "summary": "Create user"},
                ],
            },
        )
    )
    await db.commit()

    trigger = await client.post(
        f"/api/v1/projects/{project_id}/workflows",
        json={"stages": ["plan"], "target_languages": ["python"]},
        headers=headers,
    )
    assert trigger.status_code == 202, trigger.text

    logs = await client.get(f"/api/v1/projects/{project_id}/logs?limit=100", headers=headers)
    assert logs.status_code == 200, logs.text
    events = logs.json()["data"]
    types = [e["event_type"] for e in events]
    assert "workflow_started" in types
    assert "workflow_finished" in types

    planner_events = [e for e in events if e["agent_name"] == "planner_agent"]
    assert planner_events, "expected a planner_agent event"
    assert planner_events[0]["event_type"] == "stage_completed"
    assert planner_events[0]["payload"]["node_name"] == "planner_agent"


async def test_tool_calls_endpoint_returns_linked_rows(
    client: AsyncClient, db: AsyncSession
) -> None:
    user = await make_user(db, email=f"tools-{uuid.uuid4().hex[:8]}@example.com")
    org = await make_org(db, name="Tool Calls Org")
    await add_org_member(db, org=org, user=user)
    project = await make_project(db, org=org, name="Tool Calls Project")
    await add_project_member(db, project=project, user=user, role=ProjectRole.OWNER)
    run = WorkflowRun(project_id=project.id)
    db.add(run)
    await db.flush()
    event = AgentEvent(
        workflow_run_id=run.id,
        agent_name="test_agent",
        event_type="stage_completed",
        payload={"node_name": "test_agent"},
    )
    db.add(event)
    await db.flush()
    db.add(
        ToolCall(
            agent_event_id=event.id,
            tool_name="sandbox.execute_test",
            arguments={"method": "GET", "path": "/users"},
            result={"status": "passed"},
            duration_ms=25,
        )
    )
    await db.commit()

    login = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.get(f"/api/v1/workflows/{run.id}/tool-calls", headers=headers)
    assert resp.status_code == 200, resp.text
    calls = resp.json()
    assert len(calls) == 1
    assert calls[0]["tool_name"] == "sandbox.execute_test"
    assert calls[0]["arguments"] == {"method": "GET", "path": "/users"}
    assert calls[0]["duration_ms"] == 25
