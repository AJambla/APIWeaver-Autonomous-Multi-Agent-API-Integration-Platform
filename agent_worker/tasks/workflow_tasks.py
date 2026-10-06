"""Celery task that runs a full workflow via LangGraph."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from agent_worker.tasks.base import AsyncTask


class RunWorkflow(AsyncTask):
    name = "agent_worker.tasks.run_workflow"

    async def run_async(self, run_id: str, initial_state: dict, *args, **kwargs) -> dict:
        from app.core.config import get_settings
        from app.workflows.langgraph_pipeline import LangGraphOrchestrator
        from app.workflows.state import WorkflowState

        settings = get_settings()
        engine = create_async_engine(settings.database_url)
        session_factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )

        orchestrator = LangGraphOrchestrator(session_factory=session_factory)
        result = await orchestrator.run(UUID(run_id), cast(WorkflowState, initial_state))
        await engine.dispose()
        return dict(result)


run_workflow = RunWorkflow()
