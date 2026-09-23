"""Celery tasks for the document agent stage."""

from __future__ import annotations

from agent_worker.tasks.base import AsyncTask


class RunDocumentAgent(AsyncTask):
    name = "agent_worker.tasks.run_document_agent"

    async def run_async(self, run_id: str, state: dict) -> dict:
        from app.workflows.agents.doc_agent import run_doc_agent
        return await run_doc_agent(state)


run_document_agent = RunDocumentAgent()
