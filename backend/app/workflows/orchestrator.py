"""LangGraph Orchestrator and state machine runner (`Architecture.md §4`, `Feature.md §6`).

Executes agents in sequence, updates PostgreSQL checkpoints, and manages human approval gates.
Supports both synchronous and asynchronous (Celery-backed) execution modes.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any, Literal, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.models.enums import WorkflowStatus
from app.models.workflow import WorkflowCheckpoint, WorkflowRun
from app.services.event_publisher import EventPublisher
from app.services.ingestion_service import persist_normalized_spec
from app.services.qdrant_service import QdrantClient
from app.workflows.agents.planner_agent import run_planner_agent
from app.workflows.state import WorkflowState

logger = get_logger(__name__)


async def record_checkpoint(
    session: AsyncSession,
    *,
    workflow_run_id: uuid.UUID,
    node_name: str,
    state: WorkflowState | dict[str, Any],
) -> WorkflowCheckpoint:
    """Checkpoints intermediate state snapshot to PostgreSQL."""
    serializable_state = {k: v for k, v in dict(state).items() if k != "raw_document_bytes"}
    checkpoint = WorkflowCheckpoint(
        workflow_run_id=workflow_run_id,
        node_name=node_name,
        state_snapshot=serializable_state,
    )
    session.add(checkpoint)
    await session.flush()
    return checkpoint


class Orchestrator:
    """Executes the deterministic state machine for a workflow run."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        event_publisher: EventPublisher | None = None,
        execution_mode: Literal["sync", "async"] = "sync",
        qdrant_client: QdrantClient | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.event_publisher = event_publisher
        self.execution_mode = execution_mode
        self.qdrant_client = qdrant_client

    async def _emit_progress(
        self,
        run_id: uuid.UUID,
        current_dict: dict[str, Any],
        node_name: str,
    ) -> None:
        """Publish progress event if an EventPublisher is configured."""
        if self.event_publisher is None:
            return
        project_id = current_dict.get("project_id")
        progress = current_dict.get("progress_percent", 0)
        await self.event_publisher.publish_workflow_progress(
            run_id=str(run_id),
            project_id=str(project_id) if project_id else None,
            current_node=node_name,
            progress_percent=progress,
        )

    async def run(
        self,
        workflow_run_id: uuid.UUID,
        initial_state: WorkflowState,
    ) -> WorkflowState:
        """Runs the pipeline through the enabled stages."""
        if self.execution_mode == "async":
            return await self._run_async(workflow_run_id, initial_state)

        current_dict: dict[str, Any] = dict(initial_state)
        current_dict["workflow_run_id"] = str(workflow_run_id)
        current_dict["status"] = WorkflowStatus.RUNNING
        current_dict.setdefault("total_tokens_used", 0)

        if self.event_publisher is not None:
            await self.event_publisher.publish_workflow_started(
                run_id=str(workflow_run_id),
                project_id=str(current_dict.get("project_id", "")),
                stages=current_dict.get("stages", ["plan"]),
            )

        async with self.session_factory() as session:
            run_obj = await session.get(WorkflowRun, workflow_run_id)
            if run_obj:
                run_obj.status = WorkflowStatus.RUNNING
                run_obj.started_at = datetime.datetime.now(datetime.UTC)
                await session.commit()

        stages = current_dict.get("stages", ["plan"])

        try:
            # 1. Documentation Stage (always needed if normalized spec is not ready)
            if not current_dict.get("normalized_spec"):
                from app.workflows.agents.doc_agent import run_doc_agent
                doc_updates = await run_doc_agent(
                    cast(WorkflowState, current_dict),
                    qdrant_client=self.qdrant_client,
                )
                current_dict.update(doc_updates)
                current_dict["progress_percent"] = 15

                # NEW: Persist LLM-extracted spec for freeform docs
                if not current_dict.get("spec_persisted") and current_dict.get("normalized_spec"):
                    async with self.session_factory() as session:
                        await persist_normalized_spec(
                            session,
                            uuid.UUID(current_dict["project_id"]),
                            uuid.UUID(current_dict["document_id"]),
                            current_dict["normalized_spec"],
                        )
                        await session.commit()
                    current_dict["spec_persisted"] = True

                async with self.session_factory() as session:
                    await record_checkpoint(
                        session,
                        workflow_run_id=workflow_run_id,
                        node_name="doc_agent",
                        state=current_dict,
                    )
                    await session.commit()
                await self._emit_progress(workflow_run_id, current_dict, "doc_agent")

            # 2. Planner Stage (if "plan" stage is in stages)
            if "plan" in stages and current_dict.get("normalized_spec"):
                planner_updates = await run_planner_agent(cast(WorkflowState, current_dict))
                current_dict.update(planner_updates)
                current_dict["progress_percent"] = 30

                async with self.session_factory() as session:
                    await record_checkpoint(
                        session,
                        workflow_run_id=workflow_run_id,
                        node_name="planner_agent",
                        state=current_dict,
                    )
                    await session.commit()
                await self._emit_progress(workflow_run_id, current_dict, "planner_agent")

            # 3. Code Generation Stage
            if "generate" in stages and current_dict.get("plan_approved"):
                from app.workflows.agents.code_agent import run_code_agent

                plan = current_dict.get("execution_plan", {})
                phases = plan.get("phases", [])

                for phase in phases:
                    phase_number = phase.get("phase_number")
                    logger.info("code_generation_phase", phase=phase_number)
                    code_updates = await run_code_agent(
                        cast(WorkflowState, current_dict),
                        phase_number=phase_number,
                    )
                    current_dict.update(code_updates)
                    current_dict["progress_percent"] = (
                        30 + (15 * (phase_number or 1) // max(len(phases), 1))
                    )

                    async with self.session_factory() as session:
                        await record_checkpoint(
                            session,
                            workflow_run_id=workflow_run_id,
                            node_name=f"code_agent_phase_{phase_number}",
                            state=current_dict,
                        )
                        await session.commit()
                    await self._emit_progress(
                        workflow_run_id, current_dict, f"code_agent_phase_{phase_number}"
                    )

                # Cross-chunk consistency pass
                logger.info("code_generation_consistency")
                consistency_updates = await run_code_agent(
                    cast(WorkflowState, current_dict),
                    phase_number=None,
                )
                current_dict.update(consistency_updates)
                current_dict["progress_percent"] = 60

                async with self.session_factory() as session:
                    await record_checkpoint(
                        session,
                        workflow_run_id=workflow_run_id,
                        node_name="code_agent_consistency",
                        state=current_dict,
                    )
                    await session.commit()
                await self._emit_progress(workflow_run_id, current_dict, "code_agent_consistency")

            # 4. Testing Stage
            if "test" in stages and current_dict.get("generated_files"):
                from app.workflows.agents.test_agent import run_test_agent

                test_updates = await run_test_agent(cast(WorkflowState, current_dict))
                current_dict.update(test_updates)
                current_dict["progress_percent"] = 75

                async with self.session_factory() as session:
                    await record_checkpoint(
                        session,
                        workflow_run_id=workflow_run_id,
                        node_name="test_agent",
                        state=current_dict,
                    )
                    await session.commit()
                await self._emit_progress(workflow_run_id, current_dict, "test_agent")

            # 5. Export Stage
            if "export" in stages and current_dict.get("test_suite"):
                from app.workflows.agents.export_agent import ExportAgent

                export_agent = ExportAgent()
                export_updates = await export_agent.run(cast(WorkflowState, current_dict))
                current_dict.update(export_updates)
                current_dict["progress_percent"] = 95

                async with self.session_factory() as session:
                    await record_checkpoint(
                        session,
                        workflow_run_id=workflow_run_id,
                        node_name="export_agent",
                        state=current_dict,
                    )
                    await session.commit()
                await self._emit_progress(workflow_run_id, current_dict, "export_agent")

            # 6. Determine final status
            final_status = WorkflowStatus.COMPLETED
            if current_dict.get("repair_attempts"):
                escalated = any(
                    ra.get("outcome") == "escalated"
                    for ra in current_dict.get("repair_attempts", [])
                )
                if escalated:
                    final_status = WorkflowStatus.PAUSED_FOR_APPROVAL

            current_dict["status"] = final_status
            is_done = final_status == WorkflowStatus.COMPLETED
            current_dict["progress_percent"] = 100 if is_done else 90

            async with self.session_factory() as session:
                run_obj = await session.get(WorkflowRun, workflow_run_id)
                if run_obj:
                    run_obj.status = final_status
                    run_obj.total_tokens_used = current_dict.get("total_tokens_used", 0)
                    if final_status == WorkflowStatus.COMPLETED:
                        run_obj.completed_at = datetime.datetime.now(datetime.UTC)
                    await session.commit()

            if self.event_publisher is not None:
                await self.event_publisher.publish_workflow_completed(
                    run_id=str(workflow_run_id),
                    project_id=str(current_dict.get("project_id", "")),
                    status=final_status.value,
                )

            logger.info("workflow_run_finished", run_id=str(workflow_run_id), status=final_status)
            return cast(WorkflowState, current_dict)

        except Exception as exc:
            logger.error("workflow_execution_failed", run_id=str(workflow_run_id), error=str(exc))
            current_dict["status"] = WorkflowStatus.FAILED
            current_dict.setdefault("errors", []).append(str(exc))

            async with self.session_factory() as session:
                run_obj = await session.get(WorkflowRun, workflow_run_id)
                if run_obj:
                    run_obj.status = WorkflowStatus.FAILED
                    run_obj.completed_at = datetime.datetime.now(datetime.UTC)
                    await session.commit()

            if self.event_publisher is not None:
                await self.event_publisher.publish_workflow_completed(
                    run_id=str(workflow_run_id),
                    project_id=str(current_dict.get("project_id", "")),
                    status=WorkflowStatus.FAILED.value,
                )

            return cast(WorkflowState, current_dict)

    async def _run_async(
        self,
        workflow_run_id: uuid.UUID,
        initial_state: WorkflowState,
    ) -> WorkflowState:
        """Dispatch stages to Celery workers and collect results."""
        current_dict: dict[str, Any] = dict(initial_state)
        run_id_str = str(workflow_run_id)
        current_dict["workflow_run_id"] = run_id_str
        current_dict["status"] = WorkflowStatus.RUNNING
        current_dict.setdefault("total_tokens_used", 0)

        if self.event_publisher is not None:
            await self.event_publisher.publish_workflow_started(
                run_id=run_id_str,
                project_id=str(current_dict.get("project_id", "")),
                stages=current_dict.get("stages", ["plan"]),
            )

        async with self.session_factory() as session:
            run_obj = await session.get(WorkflowRun, workflow_run_id)
            if run_obj:
                run_obj.status = WorkflowStatus.RUNNING
                run_obj.started_at = datetime.datetime.now(datetime.UTC)
                await session.commit()

        try:
            # Import celery app lazily so sync mode doesn't require Celery installed.
            from agent_worker.celery_app import app as celery_app

            stages = current_dict.get("stages", ["plan"])

            if not current_dict.get("normalized_spec"):
                result = celery_app.send_task(
                    "agent_worker.tasks.run_document_agent",
                    args=[run_id_str, current_dict],
                )
                doc_updates = result.get(timeout=300)
                current_dict.update(doc_updates)
                current_dict["progress_percent"] = 15
                await self._emit_progress(workflow_run_id, current_dict, "doc_agent")

            if "plan" in stages and current_dict.get("normalized_spec"):
                result = celery_app.send_task(
                    "agent_worker.tasks.run_code_agent",
                    args=[run_id_str, current_dict],
                )
                planner_updates = result.get(timeout=300)
                current_dict.update(planner_updates)
                current_dict["progress_percent"] = 30
                await self._emit_progress(workflow_run_id, current_dict, "planner_agent")

            if "generate" in stages and current_dict.get("plan_approved"):
                plan = current_dict.get("execution_plan", {})
                phases = plan.get("phases", [])
                for phase in phases:
                    phase_number = phase.get("phase_number")
                    result = celery_app.send_task(
                        "agent_worker.tasks.run_code_agent",
                        args=[run_id_str, current_dict, phase_number],
                    )
                    code_updates = result.get(timeout=300)
                    current_dict.update(code_updates)
                    current_dict["progress_percent"] = (
                        30 + (15 * (phase_number or 1) // max(len(phases), 1))
                    )
                    await self._emit_progress(
                        workflow_run_id, current_dict, f"code_agent_phase_{phase_number}"
                    )

                result = celery_app.send_task(
                    "agent_worker.tasks.run_code_agent",
                    args=[run_id_str, current_dict, None],
                )
                consistency_updates = result.get(timeout=300)
                current_dict.update(consistency_updates)
                current_dict["progress_percent"] = 60
                await self._emit_progress(workflow_run_id, current_dict, "code_agent_consistency")

            if "test" in stages and current_dict.get("generated_files"):
                result = celery_app.send_task(
                    "agent_worker.tasks.run_testing_agent",
                    args=[run_id_str, current_dict],
                )
                test_updates = result.get(timeout=300)
                current_dict.update(test_updates)
                current_dict["progress_percent"] = 75
                await self._emit_progress(workflow_run_id, current_dict, "test_agent")

            if "export" in stages and current_dict.get("test_suite"):
                result = celery_app.send_task(
                    "agent_worker.tasks.run_export_agent",
                    args=[run_id_str, current_dict],
                )
                export_updates = result.get(timeout=300)
                current_dict.update(export_updates)
                current_dict["progress_percent"] = 95
                await self._emit_progress(workflow_run_id, current_dict, "export_agent")

            final_status = WorkflowStatus.COMPLETED
            if current_dict.get("repair_attempts"):
                escalated = any(
                    ra.get("outcome") == "escalated"
                    for ra in current_dict.get("repair_attempts", [])
                )
                if escalated:
                    final_status = WorkflowStatus.PAUSED_FOR_APPROVAL

            current_dict["status"] = final_status
            is_done = final_status == WorkflowStatus.COMPLETED
            current_dict["progress_percent"] = 100 if is_done else 90

            async with self.session_factory() as session:
                run_obj = await session.get(WorkflowRun, workflow_run_id)
                if run_obj:
                    run_obj.status = final_status
                    run_obj.total_tokens_used = current_dict.get("total_tokens_used", 0)
                    if final_status == WorkflowStatus.COMPLETED:
                        run_obj.completed_at = datetime.datetime.now(datetime.UTC)
                    await session.commit()

            if self.event_publisher is not None:
                await self.event_publisher.publish_workflow_completed(
                    run_id=run_id_str,
                    project_id=str(current_dict.get("project_id", "")),
                    status=final_status.value,
                )

            logger.info("workflow_run_finished", run_id=run_id_str, status=final_status)
            return cast(WorkflowState, current_dict)

        except Exception as exc:
            logger.error("workflow_execution_failed", run_id=run_id_str, error=str(exc))
            current_dict["status"] = WorkflowStatus.FAILED
            current_dict.setdefault("errors", []).append(str(exc))

            async with self.session_factory() as session:
                run_obj = await session.get(WorkflowRun, workflow_run_id)
                if run_obj:
                    run_obj.status = WorkflowStatus.FAILED
                    run_obj.completed_at = datetime.datetime.now(datetime.UTC)
                    await session.commit()

            if self.event_publisher is not None:
                await self.event_publisher.publish_workflow_completed(
                    run_id=run_id_str,
                    project_id=str(current_dict.get("project_id", "")),
                    status=WorkflowStatus.FAILED.value,
                )

            return cast(WorkflowState, current_dict)