"""Celery task that runs a full workflow via the Orchestrator."""

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


@app.task(base=AsyncTask, name="agent_worker.tasks.run_workflow", bind=True)
class RunWorkflow(AsyncTask):
    async def _run_async(self, run_id: str, initial_state: dict) -> dict:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from app.core.config import get_settings
        from app.workflows.orchestrator import Orchestrator
        from app.workflows.state import WorkflowState
        from app.models.workflow import WorkflowRun
        from uuid import UUID

        settings = get_settings()
        engine = create_async_engine(settings.database_url)
        session_factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )
        orchestrator = Orchestrator(session_factory, execution_mode="sync")
        result = await orchestrator.run(UUID(run_id), cast(WorkflowState, initial_state))
        await engine.dispose()
        return dict(result)


from sqlalchemy.ext.asyncio import AsyncSession
from typing import cast

run_workflow = RunWorkflow()
