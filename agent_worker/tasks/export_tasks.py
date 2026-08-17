"""Celery tasks for the export agent stage."""

from __future__ import annotations

import asyncio
from typing import Any

from celery import Task
from celery_app import app


class AsyncTask(Task):
    """Task base class that can run async functions."""

    def run(self, *args: Any, **kwargs: Any) -> Any:
        return asyncio.run(self._run_async(*args, **kwargs))

    async def _run_async(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


@app.task(base=AsyncTask, name="agent_worker.tasks.run_export_agent", bind=True)
class RunExportAgent(AsyncTask):
    async def _run_async(self, run_id: str, state: dict) -> dict:
        from app.workflows.agents.export_agent import ExportAgent
        return await ExportAgent().run(state)


run_export_agent = RunExportAgent()
