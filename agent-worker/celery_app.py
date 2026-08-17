"""Celery application for the agent-worker service."""

from __future__ import annotations

import os
from celery import Celery

BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/1")
RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/2")

app = Celery(
    "agent-worker",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
    include=[
        "agent_worker.tasks.document_tasks",
        "agent_worker.tasks.codegen_tasks",
        "agent_worker.tasks.testing_tasks",
        "agent_worker.tasks.export_tasks",
    ],
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,
    task_soft_time_limit=280,
)

if __name__ == "__main__":
    app.start()
