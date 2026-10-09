"""Run leases: one executor per run, lost executors detected, nothing stuck forever."""

from __future__ import annotations

import asyncio
import datetime
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.enums import WorkflowStatus
from app.models.workflow import WorkflowRun
from app.workflows.reaper import reap_stale_runs
from tests.conftest import make_org, make_project

NOW = datetime.datetime(2026, 10, 9, 12, 0, tzinfo=datetime.UTC)


async def _run(
    session_factory: async_sessionmaker[AsyncSession],
    status: str,
    *,
    heartbeat_at: datetime.datetime | None = None,
    created_at: datetime.datetime | None = None,
) -> uuid.UUID:
    async with session_factory() as session:
        org = await make_org(session, name=f"Lease {uuid.uuid4().hex[:6]}")
        project = await make_project(session, org=org)
        run = WorkflowRun(project_id=project.id, status=status, heartbeat_at=heartbeat_at)
        if created_at is not None:
            run.created_at = created_at
        session.add(run)
        await session.commit()
        return run.id


def _plan_state(run_id: uuid.UUID) -> dict[str, Any]:
    return {
        "workflow_run_id": str(run_id),
        "stages": ["plan"],
        "normalized_spec": {"endpoints": [{"method": "GET", "path": "/x"}]},
        "errors": [],
    }


async def test_a_run_another_executor_holds_is_not_restarted(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch
) -> None:
    """A redelivered message used to restart a claimed run from START (double spend)."""
    from app.workflows.langgraph_pipeline import LangGraphOrchestrator

    run_id = await _run(
        session_factory, WorkflowStatus.RUNNING, heartbeat_at=datetime.datetime.now(datetime.UTC)
    )
    planner_calls: list[int] = []

    async def planner(state: Any) -> dict[str, Any]:
        planner_calls.append(1)
        return {"execution_plan": {"phases": []}}

    monkeypatch.setattr("app.workflows.langgraph_pipeline.run_planner_agent", planner)

    result = await LangGraphOrchestrator(session_factory).run(run_id, _plan_state(run_id))

    assert planner_calls == []
    assert result["status"] == WorkflowStatus.RUNNING


async def test_claiming_a_queued_run_starts_its_lease_and_heartbeats(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch, test_settings
) -> None:
    from app.workflows.langgraph_pipeline import LangGraphOrchestrator

    run_id = await _run(session_factory, WorkflowStatus.QUEUED)
    beats: list[datetime.datetime | None] = []

    async def slow_planner(state: Any) -> dict[str, Any]:
        async with session_factory() as session:
            beats.append((await session.get(WorkflowRun, run_id)).heartbeat_at)
        await asyncio.sleep(1.3)
        async with session_factory() as session:
            beats.append((await session.get(WorkflowRun, run_id)).heartbeat_at)
        return {"execution_plan": {"phases": []}}

    monkeypatch.setattr("app.workflows.langgraph_pipeline.run_planner_agent", slow_planner)
    settings = test_settings.model_copy(update={"workflow_heartbeat_interval_seconds": 1})

    await LangGraphOrchestrator(session_factory, settings=settings).run(run_id, _plan_state(run_id))

    assert beats[0] is not None, "the claim stamps the lease"
    assert beats[1] is not None and beats[1] > beats[0], "a long node keeps the lease fresh"


async def test_the_reaper_fails_lost_and_never_claimed_runs_only(
    session_factory: async_sessionmaker[AsyncSession], test_settings
) -> None:
    lease = datetime.timedelta(seconds=test_settings.workflow_lease_seconds)
    queue_timeout = datetime.timedelta(seconds=test_settings.workflow_queue_timeout_seconds)

    lost = await _run(session_factory, WorkflowStatus.RUNNING, heartbeat_at=NOW - lease * 2)
    alive = await _run(session_factory, WorkflowStatus.RUNNING, heartbeat_at=NOW - lease / 2)
    never_claimed = await _run(
        session_factory, WorkflowStatus.QUEUED, created_at=NOW - queue_timeout * 2
    )
    just_queued = await _run(session_factory, WorkflowStatus.QUEUED, created_at=NOW)
    # Approved two days after creation: the approval's heartbeat restarts the clock.
    re_queued = await _run(
        session_factory,
        WorkflowStatus.QUEUED,
        created_at=NOW - datetime.timedelta(days=2),
        heartbeat_at=NOW,
    )
    paused = await _run(
        session_factory, WorkflowStatus.PAUSED_FOR_APPROVAL, heartbeat_at=NOW - lease * 10
    )

    reaped = await reap_stale_runs(session_factory, test_settings, now=NOW)

    assert reaped == 2
    async with session_factory() as session:
        status = {
            name: (await session.get(WorkflowRun, run_id)).status
            for name, run_id in {
                "lost": lost,
                "alive": alive,
                "never_claimed": never_claimed,
                "just_queued": just_queued,
                "re_queued": re_queued,
                "paused": paused,
            }.items()
        }
    assert status == {
        "lost": WorkflowStatus.FAILED,
        "alive": WorkflowStatus.RUNNING,
        "never_claimed": WorkflowStatus.FAILED,
        "just_queued": WorkflowStatus.QUEUED,
        "re_queued": WorkflowStatus.QUEUED,
        "paused": WorkflowStatus.PAUSED_FOR_APPROVAL,
    }


async def test_crash_recovery_restores_from_workflow_checkpoint(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch
) -> None:
    """When a worker restarts or redelivers a crashed run, it resumes from the latest checkpoint snapshot."""
    from app.models.workflow import WorkflowCheckpoint
    from app.workflows.langgraph_pipeline import LangGraphOrchestrator

    run_id = await _run(session_factory, WorkflowStatus.QUEUED)

    # Simulate a prior worker that saved a checkpoint for code_agent before crashing
    snapshot_state = {
        "workflow_run_id": str(run_id),
        "stages": ["plan", "generate"],
        "normalized_spec": {"endpoints": [{"method": "GET", "path": "/users"}]},
        "plan_approved": True,
        "generated_files": [{"path": "client.py", "content": "class Client: pass"}],
        "current_node": "code_agent",
        "total_tokens_used": 1500,
        "errors": [],
    }
    async with session_factory() as session:
        ckpt = WorkflowCheckpoint(
            workflow_run_id=run_id,
            node_name="code_agent",
            state_snapshot=snapshot_state,
        )
        session.add(ckpt)
        await session.commit()

    code_agent_invoked: list[int] = []

    async def mock_code_agent(state: Any) -> dict[str, Any]:
        code_agent_invoked.append(1)
        return {"generated_files": [{"path": "client.py", "content": "re-run"}]}

    monkeypatch.setattr("app.workflows.agents.code_agent.run_code_agent", mock_code_agent)

    # Executor receives the original initial_state that has empty generated_files
    initial_state = {
        "workflow_run_id": str(run_id),
        "stages": ["plan", "generate"],
        "normalized_spec": {"endpoints": [{"method": "GET", "path": "/users"}]},
        "plan_approved": True,
        "generated_files": [],
        "total_tokens_used": 0,
        "errors": [],
    }

    result = await LangGraphOrchestrator(session_factory).run(run_id, initial_state)

    # It should NOT re-run code_agent because checkpoint already finished code_agent
    assert code_agent_invoked == []
    # State should have restored generated_files and tokens from the checkpoint
    assert len(result.get("generated_files", [])) == 1
    assert result["generated_files"][0]["path"] == "client.py"
    assert result["total_tokens_used"] >= 1500
    assert result["status"] == WorkflowStatus.COMPLETED

