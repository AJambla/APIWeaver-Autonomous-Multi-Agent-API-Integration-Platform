"""Celery task that runs a full workflow via the Orchestrator."""

from __future__ import annotations

from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from agent_worker.tasks.base import AsyncTask


class RunWorkflow(AsyncTask):
    name = "agent_worker.tasks.run_workflow"

    async def run_async(self, run_id: str, initial_state: dict) -> dict:
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
run_workflow = RunWorkflow()
