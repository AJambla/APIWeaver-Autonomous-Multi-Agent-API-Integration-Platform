"""Celery tasks for the code generation agent stage."""

from __future__ import annotations

from agent_worker.tasks.base import AsyncTask


class RunCodeAgent(AsyncTask):
    name = "agent_worker.tasks.run_code_agent"

    async def run_async(self, run_id: str, state: dict, phase_number: int | None = None) -> dict:
        from app.workflows.agents.code_agent import run_code_agent
        return await run_code_agent(state, phase_number=phase_number)


run_code_agent_task = RunCodeAgent()
