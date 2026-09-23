"""Shared Celery task primitives for async workflow stages."""

from __future__ import annotations

import asyncio
from typing import Any

from celery import Task


class AsyncTask(Task):
    """Run an async task implementation in Celery's synchronous task boundary."""

    def run(self, *args: Any, **kwargs: Any) -> Any:
        return asyncio.run(self.run_async(*args, **kwargs))

    async def run_async(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError
