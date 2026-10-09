"""The metrics alerts and dashboards depend on are actually recorded."""

from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.metrics import registry


def _value(name: str, **labels: str) -> float:
    return registry.get_sample_value(name, labels) or 0.0


async def test_login_outcomes_are_counted(client: AsyncClient) -> None:
    before_fail = _value("apiweaver_auth_failure_total", reason="unknown_email")
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": f"ghost-{uuid.uuid4().hex[:6]}@example.com", "password": "wrong-password"},
    )
    assert res.status_code == 401
    assert _value("apiweaver_auth_failure_total", reason="unknown_email") == before_fail + 1


async def test_a_workflow_execution_records_outcome_duration_and_node_timings(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch
) -> None:
    from app.workflows.langgraph_pipeline import LangGraphOrchestrator
    from tests.test_workflows import _seed_project_run

    project_id, run_id = await _seed_project_run(session_factory, "metrics")

    async def planner(state: Any) -> dict[str, Any]:
        return {"execution_plan": {"phases": []}}

    monkeypatch.setattr("app.workflows.langgraph_pipeline.run_planner_agent", planner)
    runs_before = sum(
        s.value
        for m in registry.collect()
        if m.name == "apiweaver_workflow_runs"
        for s in m.samples
        if s.name == "apiweaver_workflow_runs_total"
    )
    planner_steps_before = _value("apiweaver_agent_step_duration_seconds_count", agent_type="planner_agent")

    await LangGraphOrchestrator(session_factory).run(
        uuid.UUID(run_id),
        {
            "project_id": project_id,
            "workflow_run_id": run_id,
            "stages": ["plan"],
            "normalized_spec": {"endpoints": [{"method": "GET", "path": "/x"}]},
            "errors": [],
        },
    )

    runs_after = sum(
        s.value
        for m in registry.collect()
        if m.name == "apiweaver_workflow_runs"
        for s in m.samples
        if s.name == "apiweaver_workflow_runs_total"
    )
    assert runs_after == runs_before + 1
    assert _value("apiweaver_agent_step_duration_seconds_count", agent_type="planner_agent") == (
        planner_steps_before + 1
    )
