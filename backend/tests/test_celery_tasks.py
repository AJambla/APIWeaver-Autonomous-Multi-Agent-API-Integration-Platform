"""The worker registers exactly the tasks the API dispatches."""

from __future__ import annotations

from app.workflows.dispatch import RUN_WORKFLOW_TASK


def test_the_worker_registers_the_dispatched_tasks() -> None:
    from agent_worker.celery_app import app

    assert RUN_WORKFLOW_TASK in app.tasks
    assert "agent_worker.tasks.dead_letter" in app.tasks


def test_per_stage_tasks_are_gone() -> None:
    """They were registered but nothing ever sent them (the orchestrator runs every stage)."""
    from agent_worker.celery_app import app

    for stale in ("run_document_agent", "run_planner_agent", "run_code_agent", "run_testing_agent", "run_export_agent"):
        assert f"agent_worker.tasks.{stale}" not in app.tasks
