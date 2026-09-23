"""Celery task for the workflow planning stage."""

from __future__ import annotations

from agent_worker.tasks.base import AsyncTask


class RunPlannerAgent(AsyncTask):
    name = "agent_worker.tasks.run_planner_agent"

    async def run_async(self, run_id: str, state: dict) -> dict:
        from app.workflows.agents.planner_agent import run_planner_agent

        return await run_planner_agent(state)


run_planner_agent_task = RunPlannerAgent()
