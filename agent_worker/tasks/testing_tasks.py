"""Celery tasks for the testing agent stage."""

from __future__ import annotations

from agent_worker.tasks.base import AsyncTask


class RunTestingAgent(AsyncTask):
    name = "agent_worker.tasks.run_testing_agent"

    async def run_async(self, run_id: str, state: dict) -> dict:
        from app.workflows.agents.test_agent import run_test_agent
        return await run_test_agent(state)


run_testing_agent = RunTestingAgent()
