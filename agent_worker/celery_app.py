"""Celery application for the agent-worker service."""

from __future__ import annotations

import os
from celery import Celery

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

from agent_worker.tasks.codegen_tasks import run_code_agent_task
from agent_worker.tasks.document_tasks import run_document_agent
from agent_worker.tasks.export_tasks import run_export_agent
from agent_worker.tasks.planner_tasks import run_planner_agent_task
from agent_worker.tasks.testing_tasks import run_testing_agent
from agent_worker.tasks.workflow_tasks import run_workflow

for task in (
    run_document_agent,
    run_planner_agent_task,
    run_code_agent_task,
    run_testing_agent,
    run_export_agent,
    run_workflow,
):
    app.register_task(task)

if __name__ == "__main__":
    app.start()
