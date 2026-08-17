"""Celery tasks for the code generation agent stage."""

from __future__ import annotations

import asyncio

from app.workflows.agents.code_agent import run_code_agent


def _run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def run_code_agent_task(run_id: str, state: dict, phase_number: int | None = None) -> dict:
    return _run_async(run_code_agent(state, phase_number=phase_number))
