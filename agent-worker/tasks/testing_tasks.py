"""Celery tasks for the testing agent stage."""

from __future__ import annotations

import asyncio

from app.workflows.agents.test_agent import run_test_agent


def _run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def run_testing_agent(run_id: str, state: dict) -> dict:
    return _run_async(run_test_agent(state))
