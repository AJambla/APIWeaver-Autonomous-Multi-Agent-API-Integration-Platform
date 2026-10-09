"""LangGraph-native state machine and orchestration pipeline for APIWeaver.

Defines the multi-agent execution graph with conditional routing, self-healing cycles,
approval gates, and state persistence.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import time
import uuid
from decimal import Decimal
from typing import Any, Literal, cast

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.core.config import DEFAULT_MODEL_PRICING_PER_TOKEN, Settings, get_settings
from app.core.constants import DEFAULT_TARGET_LANGUAGES, DEFAULT_WORKFLOW_STAGES
from app.core.logging import get_logger, workflow_run_id_ctx
from app.core.metrics import pipeline_error_total
from app.models.enums import ProjectStatus, WorkflowStatus
from app.models.metrics import UsageMetric
from app.models.project import Project
from app.models.spec import APISpec, Endpoint
from app.models.versioning import ArtifactVersion
from app.models.workflow import WorkflowCheckpoint, WorkflowRun
from app.services.event_publisher import EventPublisher
from app.services.ingestion_service import persist_endpoint_dependencies, persist_normalized_spec
from app.services.qdrant_service import QdrantClient
from app.services.storage_service import storage_service
from app.workflows.agents.doc_agent import run_doc_agent
from app.workflows.agents.export_agent import ExportAgent
from app.workflows.agents.planner_agent import run_planner_agent
from app.workflows.agents.test_agent import run_test_agent
from app.workflows.event_recorder import record_agent_event
from app.workflows.langgraph_logger import LangGraphAgentLogger
from app.workflows.llm import active_llm_model
from app.workflows.state import WorkflowState

logger = get_logger(__name__)
terminal_logger = LangGraphAgentLogger()

DEFAULT_TOKEN_BUDGET = 1_000_000
_TERMINAL_STATUSES = (WorkflowStatus.CANCELLED, WorkflowStatus.COMPLETED, WorkflowStatus.FAILED)
DEFAULT_TOKEN_PRICE = 0.000003
MODEL_PRICING_PER_TOKEN: dict[str, float] = DEFAULT_MODEL_PRICING_PER_TOKEN


def calculate_token_cost_usd(
    tokens: int,
    model: str | None = None,
    settings: Settings | None = None,
    pricing_overrides: dict[str, float] | None = None,
) -> Decimal:
    """Calculate estimated cost in USD based on per-model pricing loaded from Settings or overrides."""
    cfg = settings or get_settings()
    pricing = (
        pricing_overrides
        or getattr(cfg, "model_pricing_per_token", None)
        or MODEL_PRICING_PER_TOKEN
    )
    default_price = getattr(cfg, "default_token_price", DEFAULT_TOKEN_PRICE)
    price = pricing.get(model or "", default_price)
    return Decimal(str(round(tokens * price, 6)))


class WorkflowCancelledError(Exception):
    """Raised when an in-flight workflow run has been cancelled by the user or admin."""
    pass


def check_budget(state: WorkflowState, settings: Settings | None = None) -> None:
    """Check whether token budget has been exceeded."""
    cfg = settings or get_settings()
    budget = state.get("token_budget") or getattr(cfg, "default_token_budget", DEFAULT_TOKEN_BUDGET)
    used = state.get("total_tokens_used", 0)
    if used >= budget:
        raise RuntimeError(f"token_budget_exceeded: {used}/{budget}")


def _storage_tool_calls(
    previous_files: list[dict[str, Any]], updated_files: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """ToolCall rows for files the code agent newly uploaded this stage."""
    prev_paths = {f.get("file_path") for f in previous_files}
    return [
        {
            "tool_name": "storage.upload",
            "arguments": {"file_path": f.get("file_path"), "language": f.get("language")},
            "result": {"s3_key": f.get("content_s3_key")},
        }
        for f in updated_files
        if f.get("file_path") not in prev_paths
    ]


def _sandbox_tool_calls(test_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """ToolCall rows for the sandbox executions driven by the testing agent."""
    return [
        {
            "tool_name": "sandbox.execute_test",
            "arguments": {"method": r.get("method"), "path": r.get("path")},
            "result": {"status": r.get("status"), "error": r.get("error")},
            "duration_ms": r.get("latency_ms"),
        }
        for r in test_results
    ]


# --- Routing Conditions -------------------------------------------------------------


def route_from_start(state: WorkflowState) -> str:
    """Determine initial node based on requested workflow stages."""
    stages = state.get("stages", ["plan"])
    if not state.get("normalized_spec") and ("doc" in stages or "plan" in stages):
        return "doc_agent"
    if "plan" in stages and not (state.get("plan_approved") and "generate" in stages):
        return "planner_agent"
    if "generate" in stages:
        return "code_agent"
    if "test" in stages:
        return "test_agent"
    if "export" in stages:
        return "export_agent"
    return "finalize"


def route_after_planner(state: WorkflowState) -> str:
    """Determine whether to proceed to code generation, pause for approval, or finish."""
    stages = state.get("stages", ["plan"])
    if "generate" not in stages:
        return "finalize"

    # If the plan is already approved, proceed directly to code gen
    if state.get("plan_approved"):
        return "code_agent"

    # Otherwise route to human approval gate
    return "approval_gate"


def route_after_code(state: WorkflowState) -> str:
    """Determine whether to proceed to testing, export, or finish after code gen."""
    stages = state.get("stages", DEFAULT_WORKFLOW_STAGES)
    if "test" in stages:
        return "test_agent"
    if "export" in stages:
        return "export_agent"
    return "finalize"


def route_after_testing(state: WorkflowState) -> str:
    """Evaluate test results: export if passed, loop to repair if failing, or terminate."""
    stages = state.get("stages", DEFAULT_WORKFLOW_STAGES)
    test_summary = state.get("test_run_summary")
    # The test agent returns no summary when it could not run (no spec, no files, sandbox
    # crash). That is not "zero failures": untested code must never reach export (or a
    # GitHub push), so finish and let finalize record the failure.
    if not isinstance(test_summary, dict) or "failed" not in test_summary:
        return "finalize"
    failed_count = test_summary.get("failed", 0)

    # All recorded tests passed
    if failed_count == 0:
        if "export" in stages:
            return "export_agent"
        return "finalize"

    # Check repair attempts (bounded to 3)
    repair_attempts = state.get("repair_attempts", [])
    if len(repair_attempts) < 3:
        return "repair_agent"

    # Exhausted repair attempts: escalate to human approval gate
    return "approval_gate"


async def _wait_for_celery_task(
    result: Any,
    timeout: float = 300.0,
    initial_poll_interval: float = 0.2,
    max_poll_interval: float = 1.0,
) -> Any:
    """Asynchronously poll for Celery task completion without blocking an executor thread.

    `asyncio.to_thread(result.get, timeout=300)` blocks an OS worker thread in Python's
    default ThreadPoolExecutor for up to 5 minutes, leading to thread pool exhaustion
    under concurrent execution. This async helper polls `result.ready()` with cooperative
    `asyncio.sleep` intervals, yielding execution back to the event loop.
    """
    if hasattr(result, "ready"):
        start_time = time.monotonic()
        deadline = start_time + timeout
        poll_interval = initial_poll_interval

        while time.monotonic() < deadline:
            if result.ready():
                if hasattr(result, "successful") and not result.successful():
                    if hasattr(result, "failed") and result.failed():
                        task_err = getattr(result, "result", None)
                        if isinstance(task_err, BaseException):
                            raise task_err
                        raise RuntimeError(
                            f"Celery task {getattr(result, 'id', 'unknown')} failed: {task_err}"
                        )
                if hasattr(result, "result") and result.result is not None:
                    return result.result
                if hasattr(result, "get"):
                    return result.get(timeout=0.1)
                return getattr(result, "result", None)

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(poll_interval, remaining))
            poll_interval = min(poll_interval * 1.5, max_poll_interval)

        task_id = getattr(result, "id", "unknown")
        raise TimeoutError(f"Celery task {task_id} timed out after {timeout}s")

    if hasattr(result, "get"):
        return await asyncio.to_thread(result.get, timeout=timeout)
    return result


# --- Graph Factory ------------------------------------------------------------------


def create_apiweaver_graph(
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    event_publisher: EventPublisher | None = None,
    qdrant_client: QdrantClient | None = None,
) -> StateGraph:
    """Build and wire the StateGraph for APIWeaver."""
    builder = StateGraph(WorkflowState)

    async def _record_event(
        state: WorkflowState,
        *,
        agent_name: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        """Persist the AgentEvent rows the project logs read."""
        if session_factory is None or not state.get("workflow_run_id"):
            return
        try:
            async with session_factory() as session:
                await record_agent_event(
                    session,
                    workflow_run_id=uuid.UUID(str(state["workflow_run_id"])),
                    agent_name=agent_name,
                    event_type=event_type,
                    payload=payload,
                    tool_calls=tool_calls,
                )
                await session.commit()
        except Exception as exc:
            pipeline_error_total.labels(subsystem="event_record", error_type=type(exc).__name__).inc()
            logger.error("langgraph_event_record_failed", error=str(exc), exc_info=True)

    async def _emit_thought(
        state: WorkflowState,
        agent_name: str,
        message: str,
        *,
        level: str = "info",
        action: str | None = None,
        step: int | None = None,
        total_steps: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Stream real-time thought/sub-step to SSE, terminal logger, and AgentEvent table."""
        run_id = str(state.get("workflow_run_id") or "")
        project_id = str(state.get("project_id") or "")
        terminal_logger.log_thought(agent_name, run_id, message, action=action)
        if event_publisher and run_id:
            try:
                await event_publisher.publish_agent_thought(
                    run_id=run_id,
                    project_id=project_id or None,
                    agent_name=agent_name,
                    message=message,
                    level=level,
                    action=action,
                    step=step,
                    total_steps=total_steps,
                    extra=extra,
                )
            except Exception as pub_err:
                logger.warning("thought_publish_failed", error=str(pub_err))

        await _record_event(
            state,
            agent_name=agent_name,
            event_type="agent_thought",
            payload={
                "message": message,
                "level": level,
                "action": action,
                "step": step,
                "total_steps": total_steps,
                **(extra or {}),
            },
        )

    async def _save_checkpoint(state: WorkflowState, node_name: str) -> None:
        """Persist intermediate state snapshot checkpoint to PostgreSQL."""
        if session_factory is None or not state.get("workflow_run_id"):
            return
        try:
            async with session_factory() as session:
                serializable = {k: v for k, v in dict(state).items() if k != "raw_document_bytes"}
                run_uuid = uuid.UUID(str(state["workflow_run_id"]))
                checkpoint = WorkflowCheckpoint(
                    workflow_run_id=run_uuid,
                    node_name=node_name,
                    state_snapshot=serializable,
                )
                session.add(checkpoint)

                run_obj = await session.get(WorkflowRun, run_uuid)
                if run_obj:
                    run_obj.current_node = node_name
                    if "progress_percent" in state and state["progress_percent"] is not None:
                        run_obj.progress_percent = int(state["progress_percent"])
                    if "total_tokens_used" in state and state["total_tokens_used"] is not None:
                        run_obj.total_tokens_used = int(state["total_tokens_used"])
                await session.commit()
        except Exception as exc:
            pipeline_error_total.labels(subsystem="checkpoint", error_type=type(exc).__name__).inc()
            logger.error("langgraph_checkpoint_save_failed", error=str(exc), exc_info=True)

    async def _set_project_status(state: WorkflowState, status: ProjectStatus) -> None:
        """Move the project's lifecycle status as a stage starts or the run ends.

        The workspace badge, `AgentsPage`, and the `GET /projects?status=` filter all read
        this column, but only project creation and archiving ever wrote it, so a project
        stayed `draft` however far its runs got.
        """
        if session_factory is None or not state.get("project_id"):
            return
        try:
            async with session_factory() as session:
                project = await session.get(Project, uuid.UUID(str(state["project_id"])))
                if project is None or project.status == ProjectStatus.ARCHIVED:
                    return
                if project.status == status:
                    return
                project.status = status
                await session.commit()
        except Exception as exc:
            pipeline_error_total.labels(subsystem="project_status", error_type=type(exc).__name__).inc()
            logger.error(
                "project_status_update_failed",
                project_id=str(state.get("project_id")),
                status=str(status),
                error=str(exc),
                exc_info=True,
            )

    async def _assert_not_cancelled(state: WorkflowState) -> None:
        run_id = state.get("workflow_run_id")
        if not run_id or not session_factory:
            return
        try:
            async with session_factory() as session:
                run_obj = await session.get(WorkflowRun, uuid.UUID(str(run_id)))
                if run_obj and run_obj.status == WorkflowStatus.CANCELLED:
                    raise WorkflowCancelledError(f"Workflow {run_id} cancelled by user.")
        except WorkflowCancelledError:
            raise
        except Exception as exc:
            logger.debug("check_cancellation_failed", error=str(exc))

    # 1. Document Ingestion Node
    async def doc_agent_node(state: WorkflowState) -> dict[str, Any]:
        await _assert_not_cancelled(state)
        check_budget(state)
        await _set_project_status(state, ProjectStatus.PLANNING)
        run_id = state.get("workflow_run_id", "")
        doc_filename = state.get("document_filename", "unspecified_spec")
        terminal_logger.log_start(
            "doc_agent",
            run_id,
            details=f"Document: '{doc_filename}' | Parsing & Normalizing API Specification",
        )
        await _emit_thought(state, "doc_agent", f"Parsing and normalizing API specification '{doc_filename}'...", action="doc_parsing")

        tokens_before = state.get("total_tokens_used", 0)
        try:
            doc_updates = await run_doc_agent(state, qdrant_client=qdrant_client)
        except Exception as exc:
            terminal_logger.log_failure("doc_agent", run_id, exc)
            await _emit_thought(state, "doc_agent", f"Failed to normalize document: {exc}", level="error", action="doc_failed")
            raise

        tokens_after = doc_updates.get("total_tokens_used", tokens_before)
        spec = doc_updates.get("normalized_spec") or state.get("normalized_spec") or {}
        endpoints = spec.get("endpoints", [])

        if doc_updates.get("is_fallback") or not endpoints:
            terminal_logger.log_fallback(
                "doc_agent",
                run_id,
                reason="Non-standard document or heuristic normalizer triggered",
                fallback_action="Applied deterministic baseline schema extraction",
            )

        terminal_logger.log_complete(
            "doc_agent",
            run_id,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            details=f"Normalized API Spec '{spec.get('title', 'API')}' with {len(endpoints)} endpoints",
        )
        await _emit_thought(state, "doc_agent", f"Normalized API specification '{spec.get('title', 'API')}' with {len(endpoints)} endpoints.", level="success", action="doc_normalized")

        updates: dict[str, Any] = {
            **doc_updates,
            "progress_percent": 15,
            "current_node": "doc_agent",
        }

        # Persist normalized spec if freeform docs generated one
        normalized_spec = doc_updates.get("normalized_spec") or state.get("normalized_spec")
        if (
            session_factory
            and normalized_spec
            and not state.get("spec_persisted")
            and state.get("project_id")
            and state.get("document_id")
        ):
            try:
                async with session_factory() as session:
                    await persist_normalized_spec(
                        session,
                        uuid.UUID(state["project_id"]),
                        uuid.UUID(state["document_id"]),
                        normalized_spec,
                    )
                    await session.commit()
                updates["spec_persisted"] = True
            except Exception as e:
                pipeline_error_total.labels(subsystem="spec_persist", error_type=type(e).__name__).inc()
                logger.error("langgraph_spec_persist_failed", error=str(e), exc_info=True)

        if event_publisher and run_id:
            await event_publisher.publish_workflow_progress(
                run_id=run_id,
                project_id=state.get("project_id"),
                current_node="doc_agent",
                progress_percent=15,
            )

        await _record_event(
            state,
            agent_name="doc_agent",
            event_type="stage_completed",
            payload={
                "node_name": "doc_agent",
                "status": doc_updates.get("status"),
                "progress_percent": 15,
                "llm_tokens": max(tokens_after - tokens_before, 0),
                "total_tokens_used": tokens_after,
            },
        )
        await _save_checkpoint({**state, **updates}, "doc_agent")

        return updates

    # 2. Planner Agent Node
    async def planner_agent_node(state: WorkflowState) -> dict[str, Any]:
        await _assert_not_cancelled(state)
        check_budget(state)
        await _set_project_status(state, ProjectStatus.PLANNING)
        run_id = state.get("workflow_run_id", "")
        spec = dict(state.get("normalized_spec") or {})
        endpoints = spec.get("endpoints", [])
        hydrated_spec: dict[str, Any] | None = None
        if not endpoints and session_factory and state.get("project_id"):
            try:
                async with session_factory() as session:
                    api_spec_record = await session.scalar(
                        select(APISpec)
                        .where(APISpec.project_id == uuid.UUID(str(state["project_id"])))
                        .order_by(APISpec.created_at.desc())
                        .limit(1)
                    )
                    if api_spec_record:
                        # Eager-load: `ep.parameters` below would otherwise lazy-load
                        # inside async code and raise MissingGreenlet, which the except
                        # turned into a warning, so hydration never actually happened.
                        endpoint_records = (
                            await session.scalars(
                                select(Endpoint)
                                .where(Endpoint.api_spec_id == api_spec_record.id)
                                .options(selectinload(Endpoint.parameters))
                            )
                        ).all()
                        raw_data = api_spec_record.raw_normalized or {}
                        raw_eps_by_key = {
                            (str(ep.get("method", "")).upper(), ep.get("path", "")): ep
                            for ep in (raw_data.get("endpoints") or [])
                            if isinstance(ep, dict)
                        }
                        hydrated_endpoints = [
                            {
                                "id": str(ep.id),
                                "method": ep.method,
                                "path": ep.path,
                                "summary": ep.summary or raw_eps_by_key.get((str(ep.method).upper(), ep.path), {}).get("summary"),
                                "operation_id": getattr(ep, "operation_id", None) or raw_eps_by_key.get((str(ep.method).upper(), ep.path), {}).get("operation_id") or raw_eps_by_key.get((str(ep.method).upper(), ep.path), {}).get("operationId"),
                                "operationId": getattr(ep, "operation_id", None) or raw_eps_by_key.get((str(ep.method).upper(), ep.path), {}).get("operationId") or raw_eps_by_key.get((str(ep.method).upper(), ep.path), {}).get("operation_id"),
                                "parameters": [
                                    {
                                        "name": p.name,
                                        "location": p.location,
                                        "type": p.type,
                                        "required": p.required,
                                    }
                                    for p in getattr(ep, "parameters", [])
                                ] if getattr(ep, "parameters", None) else raw_eps_by_key.get((str(ep.method).upper(), ep.path), {}).get("parameters", []),
                                "request_schema": ep.request_schema if ep.request_schema is not None else raw_eps_by_key.get((str(ep.method).upper(), ep.path), {}).get("request_schema"),
                                "response_schemas": ep.response_schemas if ep.response_schemas else raw_eps_by_key.get((str(ep.method).upper(), ep.path), {}).get("response_schemas", {}),
                            }
                            for ep in endpoint_records
                        ]
                        spec = {
                            **raw_data,
                            "title": api_spec_record.title or raw_data.get("title", "API Specification"),
                            "base_url": api_spec_record.base_url or raw_data.get("base_url", ""),
                            "endpoints": hydrated_endpoints if hydrated_endpoints else raw_data.get("endpoints", []),
                        }
                        hydrated_spec = spec
                        endpoints = spec.get("endpoints", [])
            except Exception as e:
                logger.warning("planner_spec_hydration_failed", error=str(e))

        terminal_logger.log_start(
            "planner_agent",
            run_id,
            details=f"Analyzing {len(endpoints)} endpoints for topological DAG ordering & dependency clustering",
        )
        await _emit_thought(state, "planner_agent", f"Analyzing {len(endpoints)} endpoints for topological DAG ordering & dependency clustering...", action="graph_clustering")

        # Mutating `state` inside a node is not a state update: the planner saw the
        # hydrated spec, but every later node (codegen, tests, export) got the
        # endpoint-less one. Pass it explicitly and return it below.
        planner_state = (
            cast(WorkflowState, {**state, "normalized_spec": hydrated_spec})
            if hydrated_spec is not None
            else state
        )

        tokens_before = state.get("total_tokens_used", 0)
        try:
            planner_updates = await run_planner_agent(planner_state)
        except Exception as exc:
            terminal_logger.log_failure("planner_agent", run_id, exc)
            await _emit_thought(state, "planner_agent", f"Planning failed: {exc}", level="error", action="plan_failed")
            raise

        tokens_after = planner_updates.get("total_tokens_used", tokens_before)
        plan = planner_updates.get("execution_plan") or {}
        phases = plan.get("phases", [])
        nodes = plan.get("dependency_graph", {}).get("nodes", [])

        if planner_updates.get("is_fallback"):
            terminal_logger.log_fallback(
                "planner_agent",
                run_id,
                reason="Model fallback or simplified specification",
                fallback_action="Applied algorithmic dependency graph & phase DAG clustering",
            )

        terminal_logger.log_complete(
            "planner_agent",
            run_id,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            details=f"Synthesized execution plan with {len(phases)} phase(s) and {len(nodes)} DAG node(s)",
        )
        await _emit_thought(state, "planner_agent", f"Plan generated: {len(phases)} execution phase(s) and {len(nodes)} DAG node(s) mapped.", level="success", action="plan_ready")

        updates: dict[str, Any] = {
            **planner_updates,
            "progress_percent": 30,
            "current_node": "planner_agent",
        }
        if hydrated_spec is not None:
            updates["normalized_spec"] = hydrated_spec

        # Persist dependency graph if session_factory is available
        edges_written = 0
        if session_factory and state.get("project_id"):
            try:
                async with session_factory() as session:
                    edges_written = await persist_endpoint_dependencies(
                        session,
                        project_id=uuid.UUID(state["project_id"]),
                        execution_plan=planner_updates.get("execution_plan")
                        or state.get("execution_plan")
                        or {},
                        normalized_spec=planner_state.get("normalized_spec") or {},
                    )
                    await session.commit()
            except Exception as e:
                pipeline_error_total.labels(subsystem="dependency_persist", error_type=type(e).__name__).inc()
                logger.error("langgraph_dependency_persist_failed", error=str(e), exc_info=True)

        if event_publisher and run_id:
            await event_publisher.publish_workflow_progress(
                run_id=run_id,
                project_id=state.get("project_id"),
                current_node="planner_agent",
                progress_percent=30,
            )

        await _record_event(
            state,
            agent_name="planner_agent",
            event_type="stage_completed",
            payload={
                "node_name": "planner_agent",
                "status": planner_updates.get("status"),
                "progress_percent": 30,
                "edges_written": edges_written,
                "llm_tokens": max(tokens_after - tokens_before, 0),
                "total_tokens_used": tokens_after,
            },
        )
        await _save_checkpoint({**state, **updates}, "planner_agent")

        return updates

    # 3. Human Approval Gate Node (holds execution until human sign-off)
    async def approval_gate_node(state: WorkflowState) -> dict[str, Any]:
        run_id = state.get("workflow_run_id", "")
        test_summary = state.get("test_run_summary") or {}
        failed_tests = test_summary.get("failed", 0)
        is_repair_exhausted = failed_tests > 0 and len(state.get("repair_attempts", [])) >= 3
        reason = (
            f"Self-healing repair exhausted (3/3 attempts failed; {failed_tests} tests failing). Workflow paused awaiting human review"
            if is_repair_exhausted
            else "Human approval gate reached. Workflow paused awaiting project owner sign-off"
        )
        terminal_logger.log_idle(
            "approval_gate",
            run_id,
            reason=reason,
        )
        await _emit_thought(state, "approval_gate", reason, level="warn", action="approval_hold")

        updates: dict[str, Any] = {
            "status": WorkflowStatus.PAUSED_FOR_APPROVAL,
            "current_node": "approval_gate",
            "progress_percent": 80 if is_repair_exhausted else state.get("progress_percent", 30),
        }

        if event_publisher and run_id:
            await event_publisher.publish(
                run_id=run_id,
                project_id=state.get("project_id"),
                event_type="workflow.paused",
                payload={"reason": "test_repair_exhausted" if is_repair_exhausted else "human_approval_required"},
            )

        await _save_checkpoint({**state, **updates}, "approval_gate")

        return updates

    # 4. Code Generation Node (supports multi-phase and cross-chunk consistency)
    async def code_agent_node(state: WorkflowState) -> dict[str, Any]:
        await _assert_not_cancelled(state)
        check_budget(state)
        await _set_project_status(state, ProjectStatus.BUILDING)
        run_id = state.get("workflow_run_id", "")
        plan = state.get("execution_plan", {})
        phases = plan.get("phases", [])
        target_langs = state.get("target_languages") or list(DEFAULT_TARGET_LANGUAGES)
        terminal_logger.log_start(
            "code_agent",
            run_id,
            details=f"Target Languages: {target_langs} across {len(phases)} execution phase(s)",
        )
        await _emit_thought(state, "code_agent", f"Starting SDK code synthesis for {target_langs} across {len(phases)} execution phases...", action="codegen_start")

        tokens_before = state.get("total_tokens_used", 0)
        generated_files = list(state.get("generated_files", []))
        files_before = list(generated_files)
        total_tokens = tokens_before
        budget = state.get("token_budget") or DEFAULT_TOKEN_BUDGET
        execution_mode = state.get("execution_mode", "sync")

        try:
            for phase in phases:
                if total_tokens >= budget:
                    raise RuntimeError(f"token_budget_exceeded: {total_tokens}/{budget}")

                phase_num = phase.get("phase_number")
                await _emit_thought(state, "code_agent", f"Phase {phase_num}/{len(phases)}: Synthesizing {target_langs} client and models for '{phase.get('group_name', 'endpoints')}'...", action="codegen_phase", step=phase_num, total_steps=len(phases))
                if execution_mode == "async":
                    from agent_worker.celery_app import app as celery_app
                    result = celery_app.send_task(
                        "agent_worker.tasks.run_code_agent",
                        args=[str(run_id), {**state, "generated_files": generated_files, "total_tokens_used": total_tokens}, phase_num],
                        task_id=f"run_code_agent:{run_id}:phase_{phase_num}",
                    )
                    phase_result = await _wait_for_celery_task(result, timeout=300)
                else:
                    from app.workflows.agents import code_agent as code_agent_module
                    phase_result = await code_agent_module.run_code_agent(
                        {**state, "generated_files": generated_files, "total_tokens_used": total_tokens},  # type: ignore[misc]
                        phase_number=phase_num,
                        qdrant_client=qdrant_client,
                    )

                if phase_result.get("status") == "failed":
                    # run_code_agent reports its own failures ("Phase N not found", "no
                    # spec") as a status, not an exception. Reading only generated_files
                    # here reported success, and the run then failed later in testing
                    # with "No generated files to test" and the real cause lost.
                    reasons = "; ".join(str(e) for e in phase_result.get("errors") or [])
                    raise RuntimeError(
                        f"Code generation phase {phase_num} failed: {reasons or 'unknown error'}"
                    )

                for nf in phase_result.get("generated_files", []):
                    idx = next(
                        (
                            i
                            for i, f in enumerate(generated_files)
                            if f.get("file_path") == nf.get("file_path")
                            and f.get("language") == nf.get("language")
                        ),
                        None,
                    )
                    if idx is not None:
                        generated_files[idx] = nf
                    else:
                        generated_files.append(nf)
                total_tokens = phase_result.get("total_tokens_used", total_tokens)
                await _emit_thought(state, "code_agent", f"Phase {phase_num}/{len(phases)} complete ({len(generated_files)} cumulative file(s) generated).", level="success", action="phase_complete", step=phase_num, total_steps=len(phases))
                if total_tokens >= budget:
                    raise RuntimeError(f"token_budget_exceeded: {total_tokens}/{budget}")

            # Consistency pass
            if total_tokens < budget:
                await _emit_thought(state, "code_agent", "Running multi-file consistency, typing, and import alignment pass...", action="codegen_consistency")
                if execution_mode == "async":
                    from agent_worker.celery_app import app as celery_app
                    result = celery_app.send_task(
                        "agent_worker.tasks.run_code_agent",
                        args=[str(run_id), {**state, "generated_files": generated_files, "total_tokens_used": total_tokens}, None],
                        task_id=f"run_code_agent:{run_id}:consistency",
                    )
                    consistency_result = await _wait_for_celery_task(result, timeout=300)
                else:
                    from app.workflows.agents import code_agent as code_agent_module

                    # Optional polish over files every phase already produced: a
                    # truncated reply, bad JSON or an open LLM circuit here must not fail
                    # a run whose generation succeeded. Keep the phase output instead.
                    try:
                        consistency_result = await code_agent_module.run_code_agent(
                            {**state, "generated_files": generated_files, "total_tokens_used": total_tokens},  # type: ignore[misc]
                            phase_number=None,
                            qdrant_client=qdrant_client,
                        )
                    except WorkflowCancelledError:
                        raise
                    except Exception as consistency_exc:
                        logger.warning(
                            "consistency_pass_failed", run_id=run_id, error=str(consistency_exc)
                        )
                        await _emit_thought(
                            state,
                            "code_agent",
                            f"Consistency pass skipped ({consistency_exc}); keeping the phase output.",
                            level="warn",
                            action="codegen_consistency_skipped",
                        )
                        consistency_result = {}

                if consistency_result.get("status") != "failed" and consistency_result.get(
                    "generated_files"
                ):
                    generated_files = consistency_result["generated_files"]
                total_tokens = consistency_result.get("total_tokens_used", total_tokens)
                if total_tokens >= budget:
                    raise RuntimeError(f"token_budget_exceeded: {total_tokens}/{budget}")
        except Exception as exc:
            terminal_logger.log_failure("code_agent", run_id, exc)
            await _emit_thought(state, "code_agent", f"Code generation encountered an error: {exc}", level="error", action="codegen_failed")
            raise

        if any(f.get("is_fallback") for f in generated_files):
            terminal_logger.log_fallback(
                "code_agent",
                run_id,
                reason="Template-based client synthesis used",
                fallback_action="Applied jinja2 baseline SDK templates",
            )

        file_names = [f.get("file_path", "") for f in generated_files[:4]]
        preview_files = ", ".join(file_names) + ("..." if len(generated_files) > 4 else "")
        terminal_logger.log_complete(
            "code_agent",
            run_id,
            tokens_before=tokens_before,
            tokens_after=total_tokens,
            details=f"Generated {len(generated_files)} SDK file(s) ({preview_files})",
        )
        await _emit_thought(state, "code_agent", f"SDK generation complete: {len(generated_files)} source files generated ({preview_files}).", level="success", action="codegen_complete")

        updates: dict[str, Any] = {
            "generated_files": generated_files,
            "total_tokens_used": total_tokens,
            "progress_percent": 60,
            "current_node": "code_agent",
        }

        if event_publisher and run_id:
            await event_publisher.publish_workflow_progress(
                run_id=run_id,
                project_id=state.get("project_id"),
                current_node="code_agent",
                progress_percent=60,
            )

        await _record_event(
            state,
            agent_name="code_agent",
            event_type="stage_completed",
            payload={
                "node_name": "code_agent",
                "progress_percent": 60,
                "files_generated": len(generated_files),
                "llm_tokens": max(total_tokens - tokens_before, 0),
                "total_tokens_used": total_tokens,
            },
            tool_calls=_storage_tool_calls(files_before, generated_files),
        )
        await _save_checkpoint({**state, **updates}, "code_agent")

        # Persist CodeGenerationRun & GeneratedFile records for GET /projects/{id}/files
        if session_factory and run_id and generated_files:
            try:
                async with session_factory() as session:
                    from app.models.codegen import CodeGenerationRun, GeneratedFile
                    from app.models.enums import GeneratedFileType
                    run_uuid = uuid.UUID(str(run_id))
                    existing_run = await session.scalar(
                        select(CodeGenerationRun).where(CodeGenerationRun.workflow_run_id == run_uuid)
                    )
                    if existing_run is None:
                        primary_lang = target_langs[0] if (target_langs and target_langs[0] in DEFAULT_TARGET_LANGUAGES) else DEFAULT_TARGET_LANGUAGES[0]
                        existing_run = CodeGenerationRun(
                            workflow_run_id=run_uuid,
                            target_language=primary_lang,
                            status="completed",
                        )
                        session.add(existing_run)
                        await session.flush()

                    existing_entries = set((await session.execute(
                        select(GeneratedFile.language, GeneratedFile.file_path).where(GeneratedFile.code_generation_run_id == existing_run.id)
                    )).all())

                    for gf in generated_files:
                        fp = gf.get("file_path", "")
                        lang = gf.get("language") or ("python" if fp.endswith(".py") else "node")
                        s3_key = gf.get("content_s3_key", "")
                        entry_key = (lang, fp)
                        if fp and s3_key and entry_key not in existing_entries:
                            file_type_val = GeneratedFileType.SDK.value
                            if "test" in fp.lower():
                                file_type_val = GeneratedFileType.TEST.value
                            elif "docker" in fp.lower():
                                file_type_val = GeneratedFileType.DOCKERFILE.value
                            elif "readme" in fp.lower():
                                file_type_val = GeneratedFileType.README.value

                            session.add(
                                GeneratedFile(
                                    code_generation_run_id=existing_run.id,
                                    file_path=fp,
                                    content_s3_key=s3_key,
                                    language=lang,
                                    file_type=file_type_val,
                                    size_bytes=gf.get("size_bytes", 0),
                                )
                            )
                            existing_entries.add(entry_key)
                    await session.commit()
            except Exception as exc:
                pipeline_error_total.labels(subsystem="codegen_persist", error_type=type(exc).__name__).inc()
                logger.error("codegen_files_persist_failed", error=str(exc), exc_info=True)

        return updates

    # 5. Testing Node
    async def test_agent_node(state: WorkflowState) -> dict[str, Any]:
        await _assert_not_cancelled(state)
        check_budget(state)
        await _set_project_status(state, ProjectStatus.TESTING)
        run_id = state.get("workflow_run_id", "")
        backend = get_settings().sandbox_backend.upper()
        terminal_logger.log_start(
            "test_agent",
            run_id,
            details=f"Executing verification suite inside {backend} sandbox environment",
        )

        tokens_before = state.get("total_tokens_used", 0)
        await _emit_thought(state, "test_agent", f"Preparing sandbox test suite in {backend} environment...", action="test_suite_start")

        async def on_test_activity(action: str, msg: str, step: int | None, total: int | None) -> None:
            lvl = "success" if "→ PASSED" in msg else ("error" if "→ FAILED" in msg else "info")
            await _emit_thought(state, "test_agent", msg, level=lvl, action=action, step=step, total_steps=total)

        try:
            test_updates = await run_test_agent(state, session_factory=session_factory, on_activity=on_test_activity)
        except Exception as exc:
            terminal_logger.log_failure("test_agent", run_id, exc)
            await _emit_thought(state, "test_agent", f"Sandbox testing failed: {exc}", level="error", action="test_failed")
            raise

        tokens_after = test_updates.get("total_tokens_used", tokens_before)
        summary = test_updates.get("test_run_summary") or {}
        passed = summary.get("passed", 0)
        failed = summary.get("failed", 0)

        if failed > 0:
            failed_items = [
                f"{r.get('method')} {r.get('path')} ({r.get('error') or 'status mismatch'})"
                for r in test_updates.get("test_suite", [])
                if r.get("status") == "failed"
            ]
            failed_desc = "; ".join(failed_items[:3])
            terminal_logger.log_fallback(
                "test_agent",
                run_id,
                reason=f"{failed} test(s) failed inside sandbox: {failed_desc}",
                fallback_action="Triggering self-healing repair cycle via repair_agent",
            )
            grouped_errors: dict[str, int] = {}
            for r in test_updates.get("test_suite", []):
                if r.get("status") == "failed":
                    err_msg = r.get("error") or "Unknown error"
                    grouped_errors[err_msg] = grouped_errors.get(err_msg, 0) + 1
            for err_text, count in list(grouped_errors.items())[:5]:
                await _emit_thought(
                    state,
                    "test_agent",
                    f"Failure Cause [{count} test(s)]: {err_text}",
                    level="error",
                    action="failure_summary",
                )

        terminal_logger.log_complete(
            "test_agent",
            run_id,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            details=f"Sandbox test run complete: {passed} passed, {failed} failed (duration: {summary.get('duration_ms', 0)}ms)",
        )
        await _emit_thought(
            state,
            "test_agent",
            f"Sandbox testing complete: {passed} passed, {failed} failed (duration: {summary.get('duration_ms', 0)}ms).",
            level="success" if failed == 0 else "warn",
            action="test_suite_finish",
        )

        updates: dict[str, Any] = {
            **test_updates,
            "progress_percent": 75,
            "current_node": "test_agent",
        }

        if event_publisher and run_id:
            await event_publisher.publish_workflow_progress(
                run_id=run_id,
                project_id=state.get("project_id"),
                current_node="test_agent",
                progress_percent=75,
            )

        failed_tests_summary = [
            {
                "method": r.get("method"),
                "path": r.get("path"),
                "status_code": r.get("status_code"),
                "error": r.get("error"),
                "stack_trace": (r.get("stack_trace") or "")[:2000],
                "classification": r.get("classification"),
            }
            for r in test_updates.get("test_suite", [])
            if r.get("status") == "failed"
        ]

        await _record_event(
            state,
            agent_name="test_agent",
            event_type="stage_completed",
            payload={
                "node_name": "test_agent",
                "status": test_updates.get("status"),
                "progress_percent": 75,
                "llm_tokens": max(tokens_after - tokens_before, 0),
                "total_tokens_used": tokens_after,
                "test_summary": summary,
                "failed_tests": failed_tests_summary,
            },
            tool_calls=_sandbox_tool_calls(test_updates.get("test_suite", [])),
        )
        await _save_checkpoint({**state, **updates}, "test_agent")

        return updates

    # 6. Self-Healing Repair Node
    async def repair_agent_node(state: WorkflowState) -> dict[str, Any]:
        await _assert_not_cancelled(state)
        check_budget(state)
        run_id = state.get("workflow_run_id", "")
        attempts = list(state.get("repair_attempts", []))
        attempt_number = len(attempts) + 1
        terminal_logger.log_start(
            "repair_agent",
            run_id,
            details=f"Self-healing repair attempt #{attempt_number}/3 | Diagnosing failures & repairing client",
        )
        await _emit_thought(state, "repair_agent", f"Self-healing repair loop triggered (attempt #{attempt_number}/3): diagnosing failures...", level="warn", action="repair_start")

        tokens_before = state.get("total_tokens_used", 0)
        repaired_files = list(state.get("generated_files", []))
        total_tokens = tokens_before

        test_suite = state.get("test_suite", [])
        failed_tests = [r for r in test_suite if r.get("status") == "failed"]

        primary_failure = failed_tests[0] if failed_tests else {}
        error_context = f"{primary_failure.get('error', '')} {primary_failure.get('stack_trace', '')}"

        # Detect actual failing file from stack trace or error message
        target_file_path = None
        for f in repaired_files:
            fp = f.get("file_path", "")
            base_name = fp.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            if base_name and (base_name in error_context or fp in error_context):
                target_file_path = fp
                break

        if not target_file_path:
            # Prefer a client file in the failing test's language: a Node failure must
            # not send the repair to the Python client.
            failing_language = primary_failure.get("language")
            candidates = [
                f for f in repaired_files
                if not failing_language or f.get("language") in (None, failing_language)
            ] or repaired_files
            for f in candidates:
                fp = f.get("file_path", "")
                if "client" in fp.lower():
                    target_file_path = fp
                    break
            else:
                target_file_path = candidates[0].get("file_path", "client.py") if candidates else "client.py"
        failure_diagnosis = {
            "failed_tests_count": len(failed_tests),
            "method": primary_failure.get("method", "GET"),
            "path": primary_failure.get("path", "/"),
            "status_code": primary_failure.get("status_code", 0),
            "error": primary_failure.get("error", "Unknown test failure"),
            "stack_trace": primary_failure.get("stack_trace"),
            "request_snapshot": primary_failure.get("request_snapshot", {}),
            "response_snapshot": primary_failure.get("response_snapshot", {}),
            "classification": (
                primary_failure.get("classification", {}).get("classification")
                if isinstance(primary_failure.get("classification"), dict)
                else primary_failure.get("classification", "generated_code_bug")
            ) if primary_failure else "generated_code_bug",
            "reasoning": (
                primary_failure.get("classification", {}).get("reasoning")
                if isinstance(primary_failure.get("classification"), dict)
                else None
            ) if primary_failure else None,
            "prior_attempts": [
                ra.get("diff_summary") for ra in attempts
                if ra.get("target_file") == target_file_path
            ],
        }

        if failure_diagnosis.get("error"):
            await _emit_thought(
                state,
                "repair_agent",
                f"Diagnosing failure on {failure_diagnosis['method']} {failure_diagnosis['path']}: {failure_diagnosis['error']}",
                level="info",
                action="repair_diagnosis",
            )

        try:
            from app.workflows.agents import code_agent as code_agent_module
            repair_result = await code_agent_module.run_code_agent(
                {**state, "generated_files": repaired_files, "total_tokens_used": total_tokens},
                failure_diagnosis=failure_diagnosis,
                target_file=target_file_path,
                qdrant_client=qdrant_client,
            )

            total_tokens = repair_result.get("total_tokens_used", total_tokens)
            # run_code_agent reports problems (no spec, target not found) as an error
            # dict rather than raising; that is a failed attempt, not an applied fix.
            if repair_result.get("status") == "failed" or (
                repair_result.get("errors") and not repair_result.get("generated_files")
            ):
                raise RuntimeError(
                    "; ".join(str(e) for e in repair_result.get("errors") or [])
                    or "repair produced no changes"
                )
            if repair_result.get("generated_files"):
                repaired_files = repair_result["generated_files"]

            diff_summary = "Targeted repair applied"
            for rf in repaired_files:
                if rf.get("file_path") == target_file_path and rf.get("repair_diagnosis"):
                    diff_summary = rf["repair_diagnosis"]
                    break

            attempts.append({
                "attempt_number": attempt_number,
                "target_file": target_file_path,
                "method": failure_diagnosis["method"],
                "path": failure_diagnosis["path"],
                "classification": failure_diagnosis["classification"],
                "diff_summary": diff_summary,
                "error": primary_failure.get("error"),
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
                "outcome": "applied",
            })
        except Exception as exc:
            terminal_logger.log_failure("repair_agent", run_id, exc)
            await _emit_thought(
                state,
                "repair_agent",
                f"Repair attempt #{attempt_number}/3 encountered provider error ({exc}). Recording attempt outcome.",
                level="warn",
                action="repair_failed",
            )
            attempts.append({
                "attempt_number": attempt_number,
                "target_file": target_file_path,
                "method": failure_diagnosis["method"],
                "path": failure_diagnosis["path"],
                "classification": failure_diagnosis["classification"],
                "diff_summary": f"Repair synthesis failed: {exc}",
                "error": str(exc),
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
                "outcome": "failed",
            })

        tokens_after = total_tokens

        terminal_logger.log_complete(
            "repair_agent",
            run_id,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            details=f"Self-healing repair #{attempt_number}/3 processed for {target_file_path}; re-routing back to test_agent",
        )
        await _emit_thought(state, "repair_agent", f"Repair #{attempt_number}/3 cycle complete for {target_file_path}. Evaluating test suite...", level="info", action="repair_applied")

        updates: dict[str, Any] = {
            "generated_files": repaired_files,
            "repair_attempts": attempts,
            "total_tokens_used": tokens_after,
            "current_node": "repair_agent",
        }

        if event_publisher and run_id:
            await event_publisher.publish(
                run_id=run_id,
                project_id=state.get("project_id"),
                event_type="workflow.repair_attempt",
                payload={
                    "attempt_number": attempt_number,
                    "target_file": target_file_path,
                    "error": primary_failure.get("error"),
                },
            )

        await _record_event(
            state,
            agent_name="repair_agent",
            event_type="stage_completed",
            payload={
                "node_name": "repair_agent",
                "attempt_number": attempt_number,
                "target_file": target_file_path,
                "error": primary_failure.get("error"),
                "files_repaired": len(repaired_files),
                "llm_tokens": max(tokens_after - tokens_before, 0),
                "total_tokens_used": tokens_after,
            },
        )
        await _save_checkpoint({**state, **updates}, "repair_agent")

        return updates

    # 7. Export Node
    async def export_agent_node(state: WorkflowState) -> dict[str, Any]:
        await _assert_not_cancelled(state)
        check_budget(state)
        await _set_project_status(state, ProjectStatus.BUILDING)
        run_id = state.get("workflow_run_id", "")
        terminal_logger.log_start(
            "export_agent",
            run_id,
            details="Packaging SDK distribution bundles, wheel/npm archives, and docs",
        )
        await _emit_thought(state, "export_agent", "Building distribution packages and packaging SDK modules...", action="export_start")

        tokens_before = state.get("total_tokens_used", 0)
        try:
            export_agent = ExportAgent(session_factory=session_factory)
            export_updates = await export_agent.run(state)
        except Exception as exc:
            terminal_logger.log_failure("export_agent", run_id, exc)
            await _emit_thought(state, "export_agent", f"Export failed: {exc}", level="error", action="export_failed")
            raise

        tokens_after = export_updates.get("total_tokens_used", tokens_before)
        artifacts = export_updates.get("exports", [])

        terminal_logger.log_complete(
            "export_agent",
            run_id,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            details=f"Export packaging complete: {len(artifacts)} distribution artifact(s) published",
        )
        await _emit_thought(state, "export_agent", f"Export packaging complete: {len(artifacts)} distribution bundle(s) generated.", level="success", action="export_complete")

        updates: dict[str, Any] = {
            **export_updates,
            "progress_percent": 95,
            "current_node": "export_agent",
        }

        if event_publisher and run_id:
            await event_publisher.publish_workflow_progress(
                run_id=run_id,
                project_id=state.get("project_id"),
                current_node="export_agent",
                progress_percent=95,
            )

        await _record_event(
            state,
            agent_name="export_agent",
            event_type="stage_completed",
            payload={
                "node_name": "export_agent",
                "status": export_updates.get("status"),
                "progress_percent": 95,
                "artifacts_published": len(artifacts),
                "llm_tokens": max(tokens_after - tokens_before, 0),
                "total_tokens_used": tokens_after,
            },
        )
        await _save_checkpoint({**state, **updates}, "export_agent")

        # POST /export already created (and will finalize) one row per type; inserting
        # here as well recorded every export twice.
        if session_factory and state.get("project_id") and not state.get("export_rows_managed"):
            try:
                async with session_factory() as session:
                    from app.models.export import Export
                    for art in artifacts:
                        exp_type = art.get("type")
                        if not exp_type:
                            continue
                        primary_k = art.get("s3_key")
                        if not primary_k and art.get("artifacts") and isinstance(art["artifacts"], list) and art["artifacts"]:
                            primary_k = art["artifacts"][0].get("s3_key")
                        raw_art_status = art.get("status")
                        art_status = raw_art_status if raw_art_status in ("failed", "skipped") else "completed"
                        exp_row = Export(
                            project_id=uuid.UUID(str(state["project_id"])),
                            export_type=exp_type,
                            status=art_status,
                            s3_key=primary_k,
                        )
                        session.add(exp_row)
                    await session.commit()
            except Exception as e:
                pipeline_error_total.labels(subsystem="export_records_persist", error_type=type(e).__name__).inc()
                logger.error("pipeline_export_records_save_failed", error=str(e), exc_info=True)

        return updates

    # 8. Finalize Node
    async def finalize_node(state: WorkflowState) -> dict[str, Any]:
        run_id = state.get("workflow_run_id", "")
        current_status = state.get("status")

        export_override = bool(state.get("export_override_approved")) and bool(state.get("exports"))
        if current_status == WorkflowStatus.PAUSED_FOR_APPROVAL:
            final_status = WorkflowStatus.PAUSED_FOR_APPROVAL
        elif export_override and not state.get("errors"):
            # A project owner reviewed the failing tests and approved exporting anyway.
            final_status = WorkflowStatus.COMPLETED
        elif (state.get("test_run_summary") or {}).get("failed", 0) > 0 and len(state.get("repair_attempts", [])) >= 3:
            final_status = WorkflowStatus.FAILED
            exhausted_error = (
                "Self-healing repair loop exhausted (3/3 attempts failed). "
                f"{(state.get('test_run_summary') or {}).get('failed')} test(s) failed."
            )
        elif (
            state.get("execution_plan")
            and not state.get("plan_approved")
            and not state.get("generated_files")
            and (state.get("document_id") or "generate" in state.get("stages", []))
        ):
            final_status = WorkflowStatus.PAUSED_FOR_APPROVAL
        elif (state.get("test_run_summary") or {}).get("failed", 0) > 0 and "export" not in state.get("stages", []):
            final_status = WorkflowStatus.FAILED
        elif state.get("errors"):
            final_status = WorkflowStatus.FAILED
        else:
            final_status = WorkflowStatus.COMPLETED

        if final_status == WorkflowStatus.COMPLETED:
            stages = state.get("stages", [])
            if stages == ["plan"]:
                await _set_project_status(state, ProjectStatus.PLANNING)
            else:
                await _set_project_status(state, ProjectStatus.READY)
        elif final_status == WorkflowStatus.FAILED:
            await _set_project_status(state, ProjectStatus.FAILED)
        elif final_status == WorkflowStatus.PAUSED_FOR_APPROVAL:
            # Preserve the project status corresponding to where the workflow paused
            if (state.get("test_run_summary") or {}).get("failed", 0) > 0 or state.get("repair_attempts"):
                await _set_project_status(state, ProjectStatus.TESTING)
            elif state.get("generated_files"):
                await _set_project_status(state, ProjectStatus.BUILDING)
            else:
                await _set_project_status(state, ProjectStatus.PLANNING)
        elif final_status == WorkflowStatus.CANCELLED:
            # Do not overwrite project status with PLANNING on cancellation
            pass
        else:
            await _set_project_status(state, ProjectStatus.PLANNING)

        terminal_logger.log_complete(
            "finalize",
            run_id,
            0,
            0,
            details=f"LangGraph execution finished with final status: {final_status.value.upper()}",
        )
        await _emit_thought(state, "orchestrator", f"LangGraph pipeline finished with status: {final_status.value.upper()}.", level="success" if final_status == WorkflowStatus.COMPLETED else "warn", action="workflow_finished")

        updates: dict[str, Any] = {
            "status": final_status,
            "progress_percent": 100 if final_status == WorkflowStatus.COMPLETED else int(state.get("progress_percent") or (30 if final_status == WorkflowStatus.PAUSED_FOR_APPROVAL else 0)),
            "current_node": "completed",
        }
        if "exhausted_error" in locals():
            # Through the `errors` reducer, not by mutating the state in place.
            updates["errors"] = [exhausted_error]

        if event_publisher and run_id:
            await event_publisher.publish_workflow_completed(
                run_id=run_id,
                project_id=state.get("project_id"),
                status=final_status.value,
                progress_percent=updates["progress_percent"],
            )

        await _record_event(
            state,
            agent_name="orchestrator",
            event_type="workflow_finished",
            payload={
                "status": final_status.value,
                "total_tokens_used": state.get("total_tokens_used", 0),
            },
        )
        await _save_checkpoint({**state, **updates}, updates["current_node"])

        return updates

    # --- Wire Nodes into Builder ---
    builder.add_node("doc_agent", doc_agent_node)
    builder.add_node("planner_agent", planner_agent_node)
    builder.add_node("approval_gate", approval_gate_node)
    builder.add_node("code_agent", code_agent_node)
    builder.add_node("test_agent", test_agent_node)
    builder.add_node("repair_agent", repair_agent_node)
    builder.add_node("export_agent", export_agent_node)
    builder.add_node("finalize", finalize_node)

    # --- Wire Edges ---
    builder.add_conditional_edges(
        START,
        route_from_start,
        {
            "doc_agent": "doc_agent",
            "planner_agent": "planner_agent",
            "code_agent": "code_agent",
            "test_agent": "test_agent",
            "export_agent": "export_agent",
            "finalize": "finalize",
        },
    )
    builder.add_edge("doc_agent", "planner_agent")

    builder.add_conditional_edges(
        "planner_agent",
        route_after_planner,
        {
            "code_agent": "code_agent",
            "approval_gate": "approval_gate",
            "finalize": "finalize",
        },
    )

    builder.add_edge("approval_gate", "finalize")

    builder.add_conditional_edges(
        "code_agent",
        route_after_code,
        {
            "test_agent": "test_agent",
            "export_agent": "export_agent",
            "finalize": "finalize",
        },
    )

    builder.add_conditional_edges(
        "test_agent",
        route_after_testing,
        {
            "export_agent": "export_agent",
            "repair_agent": "repair_agent",
            "approval_gate": "approval_gate",
            "finalize": "finalize",
        },
    )

    builder.add_edge("repair_agent", "test_agent")
    builder.add_edge("export_agent", "finalize")
    builder.add_edge("finalize", END)

    return builder


class LangGraphOrchestrator:
    """Orchestrator that executes workflows using compiled LangGraph state machines."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        event_publisher: EventPublisher | None = None,
        qdrant_client: QdrantClient | None = None,
        checkpointer: Any | None = None,
        execution_mode: Literal["sync", "async"] = "sync",
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.session_factory = session_factory
        self.event_publisher = event_publisher
        if qdrant_client is None:
            try:
                from app.services.qdrant_service import HttpQdrantClient
                qdrant_client = HttpQdrantClient(self.settings)
            except Exception as e:
                logger.warning("failed_to_initialize_qdrant_client", error=str(e))
        self.qdrant_client = qdrant_client
        # In-process step caching checkpointer for graph execution loops.
        # Cross-step durable recovery and human-in-the-loop pause/resume are persisted
        # across all workers via PostgreSQL WorkflowCheckpoint snapshots.
        self.checkpointer = checkpointer or MemorySaver()
        self.execution_mode = execution_mode

        self._builder = create_apiweaver_graph(
            session_factory=self.session_factory,
            event_publisher=self.event_publisher,
            qdrant_client=self.qdrant_client,
        )
        self.graph = self._builder.compile(checkpointer=self.checkpointer)

    async def _record_event(
        self,
        workflow_run_id: uuid.UUID,
        *,
        agent_name: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Persist a run-level AgentEvent."""
        if self.session_factory is None:
            return
        try:
            async with self.session_factory() as session:
                await record_agent_event(
                    session,
                    workflow_run_id=workflow_run_id,
                    agent_name=agent_name,
                    event_type=event_type,
                    payload=payload,
                )
                await session.commit()
        except Exception as exc:
            pipeline_error_total.labels(subsystem="event_record", error_type=type(exc).__name__).inc()
            logger.error("langgraph_event_record_failed", error=str(exc), exc_info=True)

    async def _record_usage(
        self,
        session: AsyncSession,
        run_obj: WorkflowRun,
        state: dict[str, Any],
        tokens_spent: int,
    ) -> None:
        """Bill the tokens spent by *this* execution as a UsageMetric.

        Billing the cumulative `total_tokens_used` charged pre-pause spend again every
        time an approved plan resumed. The run row still carries the cumulative total.
        """
        if tokens_spent <= 0:
            return
        try:
            org_id = state.get("organization_id")
            if not org_id:
                project_row = await session.get(Project, run_obj.project_id)
                org_id = project_row.organization_id if project_row else None
            if org_id:
                session.add(
                    UsageMetric(
                        organization_id=uuid.UUID(str(org_id)),
                        metric_name="token_cost_usd",
                        value=calculate_token_cost_usd(
                            tokens_spent, active_llm_model(self.settings), settings=self.settings
                        ),
                    )
                )
        except Exception as metric_err:
            logger.warning("failed_to_record_usage_metric", error=str(metric_err))

    async def run(
        self,
        workflow_run_id: uuid.UUID,
        initial_state: WorkflowState,
    ) -> WorkflowState:
        """Executes the workflow graph for the specified run.

        Binds `workflow_run_id` for the duration, so every log line the agents emit is
        attributable to its run (the context variable was declared but never set).
        """
        token = workflow_run_id_ctx.set(str(workflow_run_id))
        try:
            return await self._run(workflow_run_id, initial_state)
        finally:
            workflow_run_id_ctx.reset(token)

    async def _run(
        self,
        workflow_run_id: uuid.UUID,
        initial_state: WorkflowState,
    ) -> WorkflowState:
        run_id_str = str(workflow_run_id)
        current: dict[str, Any] = dict(initial_state)
        current["workflow_run_id"] = run_id_str
        current["status"] = WorkflowStatus.RUNNING
        current["execution_mode"] = self.execution_mode
        current.setdefault("total_tokens_used", 0)
        # A resumed run (plan approval) starts from a checkpoint whose total already
        # includes the pre-pause spend, which was billed when that execution paused.
        tokens_at_start = int(current.get("total_tokens_used") or 0)

        # Claim the run: QUEUED -> RUNNING, stamping the lease. Only a queued run (or a
        # RUNNING row from before leases existed, which carries no heartbeat) is claimable.
        # Claiming any non-terminal run let a redelivered Celery message (acks_late +
        # reject_on_worker_lost) restart a run another worker was executing, or one whose
        # worker had died, from START: every LLM call paid for twice, duplicate exports.
        # A refused claim acks the message, so a poison message cannot loop either.
        if self.session_factory:
            async with self.session_factory() as session:
                now = datetime.datetime.now(datetime.UTC)
                claimed = await session.execute(
                    update(WorkflowRun)
                    .where(
                        WorkflowRun.id == workflow_run_id,
                        or_(
                            WorkflowRun.status == WorkflowStatus.QUEUED,
                            and_(
                                WorkflowRun.status == WorkflowStatus.RUNNING,
                                WorkflowRun.heartbeat_at.is_(None),
                            ),
                        ),
                    )
                    .values(
                        status=WorkflowStatus.RUNNING,
                        heartbeat_at=now,
                        started_at=func.coalesce(WorkflowRun.started_at, now),
                    )
                    .execution_options(synchronize_session=False)
                )
                await session.commit()
                if claimed.rowcount == 0:
                    existing = await session.get(WorkflowRun, workflow_run_id)
                    if existing is not None:
                        logger.info(
                            "langgraph_run_not_started",
                            run_id=run_id_str,
                            status=str(existing.status),
                        )
                        current["status"] = existing.status
                        return cast(WorkflowState, current)

        await self._record_event(
            workflow_run_id,
            agent_name="orchestrator",
            event_type="workflow_started",
            payload={
                "stages": current.get("stages", ["plan"]),
                "execution_mode": self.execution_mode,
            },
        )

        if self.event_publisher:
            await self.event_publisher.publish_workflow_started(
                run_id=run_id_str,
                project_id=current.get("project_id"),
                stages=current.get("stages", ["plan"]),
            )

        config = {"configurable": {"thread_id": run_id_str}}

        # The latest full state seen while streaming. If a node raises (or the run is
        # cancelled), tokens spent by earlier nodes are still recorded from here instead
        # of from the initial state, which used to log ~0 tokens after real spend.
        latest: dict[str, Any] = current
        heartbeat = (
            asyncio.create_task(self._keep_lease(workflow_run_id))
            if self.session_factory
            else None
        )
        try:
            async for snapshot in self.graph.astream(current, config=config, stream_mode="values"):
                if isinstance(snapshot, dict):
                    latest = snapshot
            result_state = cast(WorkflowState, latest)

            final_status = result_state.get("status", WorkflowStatus.COMPLETED)

            # Persist final checkpoint and run status
            if self.session_factory:
                async with self.session_factory() as session:
                    serializable = {
                        k: v for k, v in result_state.items() if k != "raw_document_bytes"
                    }
                    checkpoint = WorkflowCheckpoint(
                        workflow_run_id=workflow_run_id,
                        node_name=result_state.get("current_node", "completed"),
                        state_snapshot=serializable,
                    )
                    session.add(checkpoint)

                    run_obj = await session.get(WorkflowRun, workflow_run_id)
                    if run_obj:
                        if run_obj.status == WorkflowStatus.CANCELLED:
                            final_status = WorkflowStatus.CANCELLED
                        else:
                            run_obj.status = final_status
                            total_tokens = result_state.get("total_tokens_used", 0)
                            run_obj.total_tokens_used = total_tokens
                            run_obj.current_node = result_state.get("current_node", "completed")
                            run_obj.progress_percent = result_state.get(
                                "progress_percent", 100 if final_status == WorkflowStatus.COMPLETED else 50
                            )

                            cost_usd = calculate_token_cost_usd(
                                total_tokens, active_llm_model(self.settings), settings=self.settings
                            )
                            run_obj.estimated_cost_usd = cost_usd

                            await self._record_usage(
                                session, run_obj, result_state, total_tokens - tokens_at_start
                            )

                            if final_status == WorkflowStatus.COMPLETED and result_state.get("generated_files"):
                                try:
                                    await session.execute(
                                        update(ArtifactVersion)
                                        .where(
                                            ArtifactVersion.project_id == run_obj.project_id,
                                            ArtifactVersion.artifact_type == "sdk",
                                            ArtifactVersion.is_active == True,  # noqa: E712
                                        )
                                        .values(is_active=False)
                                    )
                                    curr_max_v = await session.scalar(
                                        select(func.max(ArtifactVersion.version_number)).where(
                                            ArtifactVersion.project_id == run_obj.project_id,
                                            ArtifactVersion.artifact_type == "sdk",
                                        )
                                    ) or 0
                                    new_ver_num = curr_max_v + 1
                                    diff_ref_key = f"artifacts/{run_obj.project_id}/v{new_ver_num}/manifest.json"
                                    manifest_data = {
                                        "version_number": new_ver_num,
                                        "workflow_run_id": str(workflow_run_id),
                                        "project_id": str(run_obj.project_id),
                                        "generated_files": result_state.get("generated_files", []),
                                        "export_manifest": result_state.get("export_manifest"),
                                    }
                                    try:
                                        await storage_service.upload(
                                            diff_ref_key,
                                            json.dumps(manifest_data).encode("utf-8"),
                                        )
                                    except Exception as store_err:
                                        logger.warning("failed_to_upload_artifact_manifest", error=str(store_err))
                                        diff_ref_key = None

                                    new_ver = ArtifactVersion(
                                        project_id=run_obj.project_id,
                                        artifact_type="sdk",
                                        version_number=new_ver_num,
                                        diff_ref=diff_ref_key,
                                        is_active=True,
                                    )
                                    session.add(new_ver)
                                except Exception as ver_err:
                                    logger.warning("failed_to_record_artifact_version", error=str(ver_err))

                            if final_status in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED):
                                run_obj.completed_at = datetime.datetime.now(datetime.UTC)
                        await session.commit()

            return result_state

        except WorkflowCancelledError:
            logger.info("langgraph_execution_cancelled", run_id=run_id_str)
            terminal_logger.log_complete(
                "finalize",
                run_id_str,
                0,
                0,
                details="Workflow execution cancelled by user; pipeline stopped.",
            )
            current = {**latest, "status": WorkflowStatus.CANCELLED}
            total_tokens = current.get("total_tokens_used", 0)
            cost_usd = calculate_token_cost_usd(
                total_tokens, active_llm_model(self.settings), settings=self.settings
            )
            if self.session_factory:
                async with self.session_factory() as session:
                    run_obj = await session.get(WorkflowRun, workflow_run_id)
                    if run_obj:
                        if run_obj.status != WorkflowStatus.CANCELLED:
                            run_obj.status = WorkflowStatus.CANCELLED
                        run_obj.total_tokens_used = total_tokens
                        run_obj.estimated_cost_usd = cost_usd
                        run_obj.completed_at = datetime.datetime.now(datetime.UTC)
                        await self._record_usage(
                            session, run_obj, current, total_tokens - tokens_at_start
                        )
                        await session.commit()
            await self._record_event(
                workflow_run_id,
                agent_name="orchestrator",
                event_type="workflow_finished",
                payload={"status": "cancelled", "reason": "user_cancelled", "total_tokens": total_tokens, "cost_usd": str(cost_usd)},
            )
            return cast(WorkflowState, current)

        except Exception as exc:
            logger.error("langgraph_execution_failed", run_id=run_id_str, error=str(exc))
            current = {
                **latest,
                "status": WorkflowStatus.FAILED,
                "errors": [*(latest.get("errors") or []), str(exc)],
            }
            total_tokens = current.get("total_tokens_used", 0)
            cost_usd = calculate_token_cost_usd(
                total_tokens, active_llm_model(self.settings), settings=self.settings
            )

            if self.session_factory:
                async with self.session_factory() as session:
                    run_obj = await session.get(WorkflowRun, workflow_run_id)
                    if run_obj and run_obj.status == WorkflowStatus.CANCELLED:
                        # Cancelled mid-node: keep the user's decision, record the spend.
                        run_obj.total_tokens_used = total_tokens
                        run_obj.estimated_cost_usd = cost_usd
                        run_obj = None
                        current["status"] = WorkflowStatus.CANCELLED
                    if run_obj:
                        run_obj.status = WorkflowStatus.FAILED
                        run_obj.total_tokens_used = total_tokens
                        run_obj.estimated_cost_usd = cost_usd
                        run_obj.current_node = current.get("current_node") or "failed"
                        run_obj.progress_percent = current.get("progress_percent") or 75
                        run_obj.completed_at = datetime.datetime.now(datetime.UTC)
                        await self._record_usage(
                            session, run_obj, current, total_tokens - tokens_at_start
                        )
                    try:
                        project = await session.get(
                            Project, uuid.UUID(str(current.get("project_id")))
                        )
                    except (TypeError, ValueError):
                        project = None
                    # A node that raises never reaches finalize_node, so this path has to
                    # settle the project status itself or it stays on the crashed stage.
                    if project is not None and project.status != ProjectStatus.ARCHIVED:
                        project.status = ProjectStatus.FAILED
                    await session.commit()

            await self._record_event(
                workflow_run_id,
                agent_name="orchestrator",
                event_type="workflow_failed",
                payload={"error": str(exc), "status": WorkflowStatus.FAILED.value},
            )

            if self.event_publisher:
                await self.event_publisher.publish_workflow_completed(
                    run_id=run_id_str,
                    project_id=current.get("project_id"),
                    status=WorkflowStatus.FAILED.value,
                )

            return cast(WorkflowState, current)
        finally:
            if heartbeat is not None:
                heartbeat.cancel()

    async def _keep_lease(self, workflow_run_id: uuid.UUID) -> None:
        """Refresh heartbeat_at while the graph runs; a single node can take many minutes."""
        interval = max(1, self.settings.workflow_heartbeat_interval_seconds)
        assert self.session_factory is not None
        while True:
            await asyncio.sleep(interval)
            try:
                async with self.session_factory() as session:
                    await session.execute(
                        update(WorkflowRun)
                        .where(
                            WorkflowRun.id == workflow_run_id,
                            WorkflowRun.status == WorkflowStatus.RUNNING,
                        )
                        .values(heartbeat_at=datetime.datetime.now(datetime.UTC))
                        .execution_options(synchronize_session=False)
                    )
                    await session.commit()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - a missed beat is not fatal
                logger.warning("workflow_heartbeat_failed", error=str(exc))


Orchestrator = LangGraphOrchestrator
