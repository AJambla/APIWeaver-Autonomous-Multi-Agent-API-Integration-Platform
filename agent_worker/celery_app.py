"""Celery application for the agent-worker service."""

from __future__ import annotations

import os
from celery import Celery

from agent_worker.tasks.document_tasks import run_document_agent
from agent_worker.tasks.codegen_tasks import run_code_agent_task
from agent_worker.tasks.testing_tasks import run_testing_agent
from agent_worker.tasks.export_tasks import run_export_agent
from agent_worker.tasks.workflow_tasks import run_workflow

BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/1")
RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/2")

app = Celery(
    "agent_worker",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
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

app.tasks.register(run_document_agent)
app.tasks.register(run_code_agent_task)
app.tasks.register(run_testing_agent)
app.tasks.register(run_export_agent)
app.tasks.register(run_workflow)

if __name__ == "__main__":
    app.start()
