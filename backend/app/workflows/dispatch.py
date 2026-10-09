"""Where a workflow run executes: the Celery agent worker, or (development) in-process.

Every route that starts or resumes a run goes through `dispatch_run`. Production and any
deployment with `REQUIRE_CELERY_WORKER=true` (or `WORKFLOW_DISPATCH=celery`) always
enqueue to the agent worker: a multi-minute LLM/sandbox pipeline must not run on an API
process's BackgroundTasks, where a deploy or crash silently drops it. Development keeps
the in-process path so the stack runs without a worker.

Runs are idempotent at the run level — the orchestrator claims a run with a conditional
update and refuses terminal ones — so a redelivered Celery message cannot resurrect a
cancelled run.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import celery_client
from app.core.config import Settings
from app.core.errors import DependencyUnavailableError
from app.core.logging import get_logger
from app.models.enums import WorkflowStatus
from app.models.export import Export
from app.models.testing import TestRun
from app.models.workflow import WorkflowRun
from app.services.event_publisher import EventPublisher
from app.workflows.state import WorkflowState

logger = get_logger(__name__)

RUN_WORKFLOW_TASK = "agent_worker.tasks.run_workflow"

# Keys that are not JSON-serializable or too large for a broker message. The worker
# reloads the uploaded document from object storage via `document_s3_key` instead.
_NON_PORTABLE_KEYS = ("raw_document_bytes",)


def uses_celery(settings: Settings, requested_mode: str | None = None) -> bool:
    return (
        settings.is_production
        or settings.require_celery_worker
        or settings.workflow_dispatch == "celery"
        or requested_mode == "async"
    )


def portable_state(state: WorkflowState) -> dict[str, Any]:
    return {k: v for k, v in state.items() if k not in _NON_PORTABLE_KEYS}


async def execute_run(
    run_id: uuid.UUID,
    state: WorkflowState,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    event_publisher: EventPublisher | None,
    post_run: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> WorkflowState:
    """Run the graph for `run_id`, then the route-specific bookkeeping in `post_run`."""
    from app.workflows.langgraph_pipeline import LangGraphOrchestrator

    orchestrator = LangGraphOrchestrator(
        session_factory=session_factory,
        event_publisher=event_publisher,
        settings=settings,
    )
    result = await orchestrator.run(run_id, state)
    if post_run:
        await apply_post_run(post_run, result, session_factory)
    return result


async def apply_post_run(
    post_run: dict[str, Any],
    state: WorkflowState,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Give rows created by the triggering route a terminal status after the run."""
    kind = post_run.get("kind")
    async with session_factory() as session:
        if kind == "export":
            artifacts = {
                str(a.get("type")): a for a in (state.get("exports") or []) if isinstance(a, dict)
            }
            for export_type, export_id in (post_run.get("export_ids") or {}).items():
                export = await session.get(Export, uuid.UUID(str(export_id)))
                if export is None:
                    continue
                artifact = artifacts.get(export_type)
                if artifact is None:
                    export.status = "failed"
                    continue
                art_status = artifact.get("status")
                export.status = art_status if art_status in ("failed", "skipped") else "completed"
                primary_key = artifact.get("s3_key")
                if not primary_key and isinstance(artifact.get("artifacts"), list) and artifact["artifacts"]:
                    primary_key = artifact["artifacts"][0].get("s3_key")
                if primary_key:
                    export.s3_key = primary_key
        elif kind == "test":
            # run_test_agent records results itself; this closes the paths where the
            # stage never executed, which would otherwise show "running" forever.
            test_run = await session.get(TestRun, uuid.UUID(str(post_run["test_run_id"])))
            if test_run is not None and test_run.status == "running":
                errors = [str(e) for e in (state.get("errors") or [])]
                test_run.status = "failed"
                test_run.summary = {"errors": errors or ["The test stage did not execute."]}
                test_run.completed_at = datetime.datetime.now(datetime.UTC)
        await session.commit()


async def dispatch_run(
    *,
    run_id: uuid.UUID,
    state: WorkflowState,
    settings: Settings,
    session: AsyncSession,
    background_tasks: BackgroundTasks,
    redis_client: Any,
    post_run: dict[str, Any] | None = None,
    requested_mode: str | None = None,
) -> None:
    """Enqueue the run on the agent worker, or schedule it in-process (development).

    The caller must have committed the run row first, so the worker sees it.
    """
    if uses_celery(settings, requested_mode):
        try:
            await celery_client.send_task(
                settings,
                RUN_WORKFLOW_TASK,
                args=[str(run_id), portable_state(state), post_run],
                # Unique per dispatch: an approval resumes the same run id, and a reused
                # task id would return the first dispatch's cached result.
                task_id=f"run_workflow:{run_id}:{uuid.uuid4().hex[:12]}",
            )
            return
        except Exception as exc:
            required = settings.is_production or settings.require_celery_worker or (
                settings.workflow_dispatch == "celery"
            )
            if required:
                # Do not leave an orphaned QUEUED run behind a 503.
                run = await session.get(WorkflowRun, run_id)
                if run is not None and run.status == WorkflowStatus.QUEUED:
                    run.status = WorkflowStatus.FAILED
                    run.completed_at = datetime.datetime.now(datetime.UTC)
                    await session.commit()
                # The broker error names hosts and ports; it belongs in the log, not the response.
                logger.error("celery_dispatch_failed", run_id=str(run_id), error=str(exc))
                raise DependencyUnavailableError(
                    "The workflow queue is unavailable. Please retry shortly."
                ) from exc
            logger.warning("celery_dispatch_failed_running_inline", run_id=str(run_id), error=str(exc))

    engine_session_factory = async_sessionmaker(
        bind=session.bind, class_=AsyncSession, expire_on_commit=False
    )
    background_tasks.add_task(
        execute_run,
        run_id,
        state,
        session_factory=engine_session_factory,
        event_publisher=EventPublisher(redis_client),
        post_run=post_run,
        settings=settings,
    )
