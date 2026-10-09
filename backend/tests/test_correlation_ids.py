"""One request id and one run id follow the work through the broker into agent logs."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import request_id_ctx, workflow_run_id_ctx


async def test_the_orchestrator_binds_the_run_id_while_it_runs(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch
) -> None:
    """workflow_run_id_ctx was declared 'set by the orchestrator' but never set."""
    from app.workflows.langgraph_pipeline import LangGraphOrchestrator
    from tests.test_workflows import _seed_project_run

    project_id, run_id = await _seed_project_run(session_factory, "ctx")
    seen: list[str] = []

    async def fake_planner(state: Any) -> dict[str, Any]:
        seen.append(workflow_run_id_ctx.get())
        return {"execution_plan": {"phases": []}, "total_tokens_used": 0}

    monkeypatch.setattr("app.workflows.langgraph_pipeline.run_planner_agent", fake_planner)
    state = {
        "project_id": project_id,
        "workflow_run_id": run_id,
        "stages": ["plan"],
        "normalized_spec": {"endpoints": [{"method": "GET", "path": "/x"}]},
        "errors": [],
    }

    await LangGraphOrchestrator(session_factory).run(uuid.UUID(run_id), state)

    assert seen == [run_id]
    assert workflow_run_id_ctx.get() == ""


async def test_the_producer_forwards_the_request_id_as_a_header(monkeypatch, test_settings) -> None:
    from app.core import celery_client

    sent: list[dict[str, Any]] = []

    class _Producer:
        def send_task(self, name: str, **kwargs: Any) -> None:
            sent.append(kwargs)

    monkeypatch.setattr(celery_client, "get_producer", lambda _url: _Producer())
    token = request_id_ctx.set("req_abc123")
    try:
        await celery_client.send_task(test_settings, "t", args=[], task_id="id-1")
    finally:
        request_id_ctx.reset(token)

    assert sent[0]["headers"] == {"request_id": "req_abc123"}


def test_the_worker_binds_and_unbinds_both_ids_per_task() -> None:
    from agent_worker import celery_app

    task = SimpleNamespace(
        name="agent_worker.tasks.run_workflow",
        request=SimpleNamespace(request_id="req_from_api"),
    )
    celery_app._bind_correlation_ids(task_id="task-1", task=task, args=["run-123", {}, None])
    try:
        assert request_id_ctx.get() == "req_from_api"
        assert workflow_run_id_ctx.get() == "run-123"
    finally:
        celery_app._unbind_correlation_ids(task_id="task-1")

    assert request_id_ctx.get() == ""
    assert workflow_run_id_ctx.get() == ""
