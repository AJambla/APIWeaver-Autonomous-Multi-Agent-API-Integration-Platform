"""Celery tasks for the testing agent stage."""

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


@app.task(base=AsyncTask, name="agent_worker.tasks.run_testing_agent", bind=True)
class RunTestingAgent(AsyncTask):
    async def _run_async(self, run_id: str, state: dict) -> dict:
        from app.workflows.agents.test_agent import run_test_agent
        return await run_test_agent(state)


run_testing_agent = RunTestingAgent()
