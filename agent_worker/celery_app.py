"""Celery application for the agent-worker service."""

from __future__ import annotations

import os
from typing import Any

from celery import Celery, signals

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
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_routes={
        "agent_worker.tasks.dead_letter": {"queue": "dlq"},
    },
    # Must exceed the longest task's time limit (run_workflow: up to an hour), or Redis
    # redelivers a still-running workflow to a second worker.
    broker_transport_options={
        "visibility_timeout": int(os.environ.get("WORKFLOW_TASK_TIME_LIMIT_SECONDS", "3600")) + 900
    },
    # One long workflow per prefetch slot: do not reserve a second behind it.
    worker_prefetch_multiplier=1,
)

@signals.setup_logging.connect
def _keep_celery_off_the_root_logger(**_: Any) -> None:
    """Connecting this stops Celery from installing its own root handlers; ours follow."""


@signals.worker_process_init.connect
@signals.worker_init.connect
def _configure_worker_logging(**_: Any) -> None:
    """Install the API's structlog pipeline (JSON + secret redaction) in the worker.

    configure_logging was only ever called by the API, so worker logs used structlog's
    console defaults with no redaction (Security.md §19), including task error strings.
    """
    from app.core.logging import configure_logging

    configure_logging(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        json_output=os.environ.get("APP_ENV", "development") != "development",
    )


_correlation_tokens: dict[str, list[Any]] = {}


@signals.task_prerun.connect
def _bind_correlation_ids(task_id: str | None = None, task: Any = None, args: Any = None, **_: Any) -> None:
    from app.core.logging import request_id_ctx, workflow_run_id_ctx

    request_id = getattr(getattr(task, "request", None), "request_id", None)
    run_id = args[0] if task is not None and task.name == "agent_worker.tasks.run_workflow" and args else None
    tokens = []
    if request_id:
        tokens.append((request_id_ctx, request_id_ctx.set(str(request_id))))
    if run_id:
        tokens.append((workflow_run_id_ctx, workflow_run_id_ctx.set(str(run_id))))
    if task_id:
        _correlation_tokens[task_id] = tokens


@signals.task_postrun.connect
def _unbind_correlation_ids(task_id: str | None = None, **_: Any) -> None:
    for var, token in reversed(_correlation_tokens.pop(task_id or "", [])):
        var.reset(token)


# Imported after `app` exists: the tasks register against it.
from agent_worker.tasks.codegen_tasks import run_code_agent_task  # noqa: E402
from agent_worker.tasks.dlq_tasks import dead_letter_task  # noqa: E402
from agent_worker.tasks.document_tasks import run_document_agent  # noqa: E402
from agent_worker.tasks.export_tasks import run_export_agent  # noqa: E402
from agent_worker.tasks.planner_tasks import run_planner_agent_task  # noqa: E402
from agent_worker.tasks.testing_tasks import run_testing_agent  # noqa: E402
from agent_worker.tasks.workflow_tasks import run_workflow  # noqa: E402

for task in (
    run_document_agent,
    run_planner_agent_task,
    run_code_agent_task,
    run_testing_agent,
    run_export_agent,
    run_workflow,
    dead_letter_task,
):
    app.register_task(task)

if __name__ == "__main__":
    app.start()
