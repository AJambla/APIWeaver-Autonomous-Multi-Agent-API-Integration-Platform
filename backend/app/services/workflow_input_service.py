"""Rebuild the orchestrator's input artifacts from persisted project state.

The single-stage endpoints (`/test`, `/export`) start a run that skips the earlier
stages, so their initial state has to be reloaded from the database. Handed empty
lists instead, the orchestrator re-runs the documentation agent and every downstream
guard (`generated_files`, `test_suite`) sees nothing, so the stage silently does no
work while the API still answers 202.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.orm import selectinload

from app.models.codegen import CodeGenerationRun, GeneratedFile
from app.models.spec import APISpec, Endpoint, EndpointParameter
from app.models.testing import TestResult, TestRun
from app.models.workflow import WorkflowRun


def endpoint_labels(
    endpoints: list[Endpoint] | tuple[Endpoint, ...]
) -> dict[tuple[str, str], uuid.UUID]:
    """Map "METHOD path" labels onto persisted endpoint ids (first row wins)."""
    mapping: dict[tuple[str, str], uuid.UUID] = {}
    for ep in endpoints:
        mapping.setdefault((str(ep.method).upper(), ep.path), ep.id)
    return mapping


async def load_normalized_spec(
    session: AsyncSession, project_id: uuid.UUID
) -> dict[str, Any] | None:
    """The project's most recent normalized specification."""
    spec = await session.scalar(
        select(APISpec)
        .where(APISpec.project_id == project_id)
        .order_by(APISpec.created_at.desc())
        .limit(1)
    )
    if not spec:
        return None
    raw = dict(spec.raw_normalized) if isinstance(spec.raw_normalized, dict) else {}
    raw_eps = raw.get("endpoints", [])
    needs_hydration = not raw_eps or any(
        isinstance(ep, dict) and ("parameters" not in ep or "request_schema" not in ep)
        for ep in raw_eps
    )
    if needs_hydration:
        endpoints_stmt = (
            select(Endpoint)
            .where(Endpoint.api_spec_id == spec.id)
            .options(selectinload(Endpoint.parameters))
        )
        db_endpoints = (await session.execute(endpoints_stmt)).scalars().all()
        if db_endpoints:
            raw_by_key = {
                (str(ep.get("method", "")).upper(), ep.get("path", "")): ep
                for ep in raw_eps
                if isinstance(ep, dict)
            }
            hydrated = []
            for db_ep in db_endpoints:
                m = str(db_ep.method).upper()
                p = db_ep.path
                matched_raw = raw_by_key.get((m, p), {})
                op_id = getattr(db_ep, "operation_id", None) or matched_raw.get("operation_id") or matched_raw.get("operationId")
                hydrated.append({
                    "id": str(db_ep.id),
                    "method": m,
                    "path": p,
                    "operation_id": op_id,
                    "operationId": op_id,
                    "summary": db_ep.summary or matched_raw.get("summary"),
                    "request_schema": db_ep.request_schema if db_ep.request_schema is not None else matched_raw.get("request_schema"),
                    "response_schemas": db_ep.response_schemas if db_ep.response_schemas else matched_raw.get("response_schemas", {}),
                    "parameters": [
                        {
                            "name": param.name,
                            "location": param.location,
                            "type": param.type,
                            "required": param.required,
                        }
                        for param in db_ep.parameters
                    ] if db_ep.parameters else matched_raw.get("parameters", []),
                })
            raw["endpoints"] = hydrated
    return raw


async def load_generated_files(
    session: AsyncSession, project_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Files from the most recent workflow run that generated any.

    Mirrors the shape the code agent leaves in workflow state, which is what the
    testing and export agents read.
    """
    workflow_run_id = await session.scalar(
        select(CodeGenerationRun.workflow_run_id)
        .join(WorkflowRun, CodeGenerationRun.workflow_run_id == WorkflowRun.id)
        .where(WorkflowRun.project_id == project_id)
        .order_by(WorkflowRun.created_at.desc())
        .limit(1)
    )
    if workflow_run_id is None:
        return []

    rows = await session.scalars(
        select(GeneratedFile)
        .where(GeneratedFile.code_generation_run_id.in_(
            select(CodeGenerationRun.id).where(
                CodeGenerationRun.workflow_run_id == workflow_run_id
            )
        ))
        .order_by(GeneratedFile.file_path)
    )
    return [
        {
            "file_path": row.file_path,
            "content_s3_key": row.content_s3_key,
            "language": row.language,
            "file_type": row.file_type,
        }
        for row in rows
    ]


async def load_latest_test_results(
    session: AsyncSession, project_id: uuid.UUID
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """(test_suite, summary) from the project's most recent test run."""
    test_run = await session.scalar(
        select(TestRun)
        .where(TestRun.project_id == project_id)
        .order_by(TestRun.started_at.desc())
        .limit(1)
    )
    if test_run is None:
        return [], None

    results = list(
        (
            await session.execute(
                select(TestResult).where(TestResult.test_run_id == test_run.id)
            )
        ).scalars()
    )

    spec = await session.scalar(
        select(APISpec)
        .where(APISpec.project_id == project_id)
        .order_by(APISpec.created_at.desc())
        .limit(1)
    )
    labels: dict[uuid.UUID, tuple[str, str]] = {}
    if spec is not None:
        for ep in await session.scalars(select(Endpoint).where(Endpoint.api_spec_id == spec.id)):
            labels[ep.id] = (str(ep.method).upper(), ep.path)

    suite: list[dict[str, Any]] = []
    for row in results:
        method, path = labels.get(row.endpoint_id, ("GET", "/")) if row.endpoint_id else ("GET", "/")
        snapshot = row.response_snapshot or {}
        suite.append(
            {
                "endpoint_id": str(row.endpoint_id) if row.endpoint_id else None,
                "method": method,
                "path": path,
                "status": row.status,
                "status_code": row.status_code,
                "latency_ms": row.latency_ms,
                "response_snapshot": snapshot,
                "error": snapshot.get("error"),
                "stack_trace": snapshot.get("stack_trace"),
            }
        )
    return suite, test_run.summary
