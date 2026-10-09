"""Write the testing agent's outcomes back into `test_runs` / `test_results`.

Before this, `run_test_agent` returned results only in workflow state, so the rows the
`GET /projects/{id}/test-runs/{run_id}` route reads were never written and the Test tab
could not show anything even when the suite ran.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.core.metrics import pipeline_error_total
from app.models.enums import RepairOutcome, TestEnvironment, TestResultStatus
from app.models.spec import APISpec, Endpoint
from app.models.testing import RepairAttempt, TestResult, TestRun
from app.services.workflow_input_service import endpoint_labels

logger = get_logger(__name__)

# Mirrors the cap `route_after_testing` enforces; a service must not import the graph.
MAX_REPAIR_ATTEMPTS = 3


async def record_test_run_results(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    workflow_run_id: str | uuid.UUID | None,
    project_id: str | uuid.UUID | None,
    test_suite: list[dict[str, Any]] | None = None,
    summary: dict[str, Any] | None = None,
    status: str | None = None,
    errors: list[str] | None = None,
    repair_attempts: list[dict[str, Any]] | None = None,
    environment: str = TestEnvironment.SANDBOX.value,
) -> None:
    """Persist one test run's results against the run that produced them.

    Reuses the `TestRun` the `/test` route created (matched on `workflow_run_id`) so the
    requested environment survives; creates one when the tests ran as part of a resumed
    workflow, which never had a row.

    `repair_attempts` are the self-healing loops carried in workflow state; `GET
    /test-runs/{run_id}/repairs` reads them from `repair_attempts`, which nothing wrote.
    """
    try:
        run_uuid = uuid.UUID(str(workflow_run_id))
        project_uuid = uuid.UUID(str(project_id))
    except (TypeError, ValueError):
        logger.warning("test_run_results_skipped", workflow_run_id=str(workflow_run_id))
        return

    try:
        async with session_factory() as session:
            test_run = await session.scalar(
                select(TestRun)
                .where(TestRun.workflow_run_id == run_uuid)
                .order_by(TestRun.started_at.desc())
                .limit(1)
            )
            if test_run is None:
                test_run = TestRun(
                    project_id=project_uuid,
                    workflow_run_id=run_uuid,
                    environment=environment,
                    status="running",
                )
                session.add(test_run)
                await session.flush()

            await _write_results(
                session, test_run, project_uuid, test_suite or [], repair_attempts or []
            )

            test_run.status = status or "completed"
            test_run.summary = {**(summary or {}), "errors": list(errors)} if errors else summary
            test_run.completed_at = datetime.datetime.now(datetime.UTC)
            await session.commit()
    except Exception as exc:
        logger.error(
            "test_run_persistence_failed",
            workflow_run_id=str(workflow_run_id),
            error=str(exc),
        )
        await _mark_failed(session_factory, run_uuid, project_uuid, str(exc))


async def _write_results(
    session: AsyncSession,
    test_run: TestRun,
    project_id: uuid.UUID,
    test_suite: list[dict[str, Any]],
    repair_attempts: list[dict[str, Any]],
) -> None:
    previous_result_ids = select(TestResult.id).where(TestResult.test_run_id == test_run.id)
    await session.execute(
        delete(RepairAttempt).where(
            RepairAttempt.test_result_id.in_(previous_result_ids)
        )
    )
    await session.execute(
        delete(TestResult).where(TestResult.test_run_id == test_run.id)
    )
    if not test_suite:
        return

    labels = endpoint_labels(await _endpoint_rows(session, project_id))
    rows: dict[tuple[str, str], TestResult] = {}
    for result in test_suite:
        snapshot = dict(result.get("response_snapshot") or {})
        if result.get("error"):
            snapshot["error"] = result["error"]
        if result.get("stack_trace"):
            snapshot["stack_trace"] = result["stack_trace"]
        key = (str(result.get("method", "")).upper(), str(result.get("path", "")))
        row = TestResult(
            test_run_id=test_run.id,
            endpoint_id=labels.get(key),
            status=str(result.get("status") or TestResultStatus.FAILED.value),
            status_code=result.get("status_code"),
            latency_ms=result.get("latency_ms"),
            response_snapshot=snapshot or None,
        )
        session.add(row)
        rows[key] = row

    await session.flush()
    await _write_repairs(session, rows, repair_attempts)


async def _write_repairs(
    session: AsyncSession,
    result_rows: dict[tuple[str, str], TestResult],
    repair_attempts: list[dict[str, Any]],
) -> None:
    """Attach the workflow state's self-healing loop to the endpoint that provoked it."""
    if not repair_attempts:
        return
    last_for_endpoint: dict[tuple[str, str], int] = {}
    for attempt in repair_attempts:
        attempt_key = (str(attempt.get("method", "")).upper(), str(attempt.get("path", "")))
        last_for_endpoint[attempt_key] = max(
            last_for_endpoint.get(attempt_key, 0), int(attempt.get("attempt_number") or 0)
        )
    for attempt in repair_attempts:
        key = (str(attempt.get("method", "")).upper(), str(attempt.get("path", "")))
        result_row = result_rows.get(key)
        if result_row is None:
            logger.warning(
                "repair_attempt_unmatched",
                attempt_number=attempt.get("attempt_number"),
                endpoint=" ".join(key),
            )
            continue
        session.add(
            RepairAttempt(
                test_result_id=result_row.id,
                attempt_number=int(attempt.get("attempt_number") or 0),
                failure_classification=attempt.get("classification"),
                diff_summary={
                    "target_file": attempt.get("target_file"),
                    "summary": attempt.get("diff_summary"),
                    "error": attempt.get("error"),
                },
                outcome=_repair_outcome(
                    attempt,
                    result_row,
                    is_final=int(attempt.get("attempt_number") or 0) == last_for_endpoint[key],
                ),
            )
        )


def _repair_outcome(
    attempt: dict[str, Any], result_row: TestResult, *, is_final: bool
) -> str | None:
    """Derive only what this round proves; a superseded loop's outcome is not guessed."""
    if attempt.get("outcome") == "failed":
        return RepairOutcome.STILL_FAILING.value
    if not is_final:
        return None
    if result_row.status == TestResultStatus.PASSED.value:
        return RepairOutcome.RESOLVED.value
    if int(attempt.get("attempt_number") or 0) >= MAX_REPAIR_ATTEMPTS:
        return RepairOutcome.ESCALATED.value
    return RepairOutcome.STILL_FAILING.value


async def _endpoint_rows(session: AsyncSession, project_id: uuid.UUID) -> list[Endpoint]:
    spec = await session.scalar(
        select(APISpec)
        .where(APISpec.project_id == project_id)
        .order_by(APISpec.created_at.desc())
        .limit(1)
    )
    if spec is None:
        return []
    return list(await session.scalars(select(Endpoint).where(Endpoint.api_spec_id == spec.id)))


async def _mark_failed(
    session_factory: async_sessionmaker[AsyncSession],
    workflow_run_id: uuid.UUID,
    project_id: uuid.UUID,
    error: str,
) -> None:
    """Best-effort: never leave a run parked in `running` when persistence blew up."""
    try:
        async with session_factory() as session:
            test_run = await session.scalar(
                select(TestRun)
                .where(TestRun.workflow_run_id == workflow_run_id)
                .order_by(TestRun.started_at.desc())
                .limit(1)
            )
            if test_run is None:
                return
            test_run.status = "failed"
            test_run.summary = {"errors": [error]}
            test_run.completed_at = datetime.datetime.now(datetime.UTC)
            await session.commit()
    except Exception as exc:
        pipeline_error_total.labels(subsystem="test_run_service", error_type=type(exc).__name__).inc()
        logger.exception("test_run_failure_marking_failed", workflow_run_id=str(workflow_run_id))
