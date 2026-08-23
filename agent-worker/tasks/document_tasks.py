"""Celery tasks for the document agent stage."""

from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.services.qdrant_service import HttpQdrantClient
from app.workflows.agents.doc_agent import run_doc_agent


def _run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def run_document_agent(run_id: str, state: dict) -> dict:
    settings = get_settings()
    qdrant_client = HttpQdrantClient(settings)
    return _run_async(run_doc_agent(state, qdrant_client=qdrant_client))
