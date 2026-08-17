"""Celery tasks for the code generation agent stage."""

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


@app.task(base=AsyncTask, name="agent_worker.tasks.run_code_agent", bind=True)
class RunCodeAgent(AsyncTask):
    async def _run_async(self, run_id: str, state: dict, phase_number: int | None = None) -> dict:
        from app.workflows.agents.code_agent import run_code_agent
        return await run_code_agent(state, phase_number=phase_number)


run_code_agent_task = RunCodeAgent()
