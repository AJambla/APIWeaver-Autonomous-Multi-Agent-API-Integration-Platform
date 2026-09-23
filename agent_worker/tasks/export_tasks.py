"""Celery tasks for the export agent stage."""

from __future__ import annotations

from agent_worker.tasks.base import AsyncTask


class RunExportAgent(AsyncTask):
    name = "agent_worker.tasks.run_export_agent"

    async def run_async(self, run_id: str, state: dict) -> dict:
        from app.workflows.agents.export_agent import ExportAgent
        return await ExportAgent().run(state)


run_export_agent = RunExportAgent()
