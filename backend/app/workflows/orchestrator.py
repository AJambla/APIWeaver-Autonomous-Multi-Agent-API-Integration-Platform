"""LangGraph Orchestrator and state machine runner (`Architecture.md §4`, `Feature.md §6`).

Executes agents in sequence, updates PostgreSQL checkpoints, and manages human approval gates.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.models.enums import WorkflowStatus
from app.models.workflow import WorkflowCheckpoint, WorkflowRun
from app.workflows.agents.doc_agent import run_doc_agent
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

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def run(
        self,
        workflow_run_id: uuid.UUID,
        initial_state: WorkflowState,
    ) -> WorkflowState:
        """Runs the pipeline through the enabled stages."""
        current_dict: dict[str, Any] = dict(initial_state)
        current_dict["workflow_run_id"] = str(workflow_run_id)
        current_dict["status"] = WorkflowStatus.RUNNING
        current_dict.setdefault("total_tokens_used", 0)

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
                doc_updates = await run_doc_agent(cast(WorkflowState, current_dict))
                current_dict.update(doc_updates)

                async with self.session_factory() as session:
                    await record_checkpoint(
                        session,
                        workflow_run_id=workflow_run_id,
                        node_name="doc_agent",
                        state=current_dict,
                    )
                    await session.commit()

            # 2. Planner Stage (if "plan" stage is in stages)
            if "plan" in stages and current_dict.get("normalized_spec"):
                planner_updates = await run_planner_agent(cast(WorkflowState, current_dict))
                current_dict.update(planner_updates)

                async with self.session_factory() as session:
                    await record_checkpoint(
                        session,
                        workflow_run_id=workflow_run_id,
                        node_name="planner_agent",
                        state=current_dict,
                    )
                    await session.commit()

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

                    async with self.session_factory() as session:
                        await record_checkpoint(
                            session,
                            workflow_run_id=workflow_run_id,
                            node_name=f"code_agent_phase_{phase_number}",
                            state=current_dict,
                        )
                        await session.commit()

                # Cross-chunk consistency pass
                logger.info("code_generation_consistency")
                consistency_updates = await run_code_agent(
                    cast(WorkflowState, current_dict),
                    phase_number=None,
                )
                current_dict.update(consistency_updates)

                async with self.session_factory() as session:
                    await record_checkpoint(
                        session,
                        workflow_run_id=workflow_run_id,
                        node_name="code_agent_consistency",
                        state=current_dict,
                    )
                    await session.commit()

            # 4. Testing Stage
            if "test" in stages and current_dict.get("generated_files"):
                from app.workflows.agents.test_agent import run_test_agent

                test_updates = await run_test_agent(cast(WorkflowState, current_dict))
                current_dict.update(test_updates)

                async with self.session_factory() as session:
                    await record_checkpoint(
                        session,
                        workflow_run_id=workflow_run_id,
                        node_name="test_agent",
                        state=current_dict,
                    )
                    await session.commit()

            # 5. Export Stage
            if "export" in stages and current_dict.get("test_suite"):
                from app.workflows.agents.export_agent import ExportAgent

                export_agent = ExportAgent()
                export_updates = await export_agent.run(cast(WorkflowState, current_dict))
                current_dict.update(export_updates)

                async with self.session_factory() as session:
                    await record_checkpoint(
                        session,
                        workflow_run_id=workflow_run_id,
                        node_name="export_agent",
                        state=current_dict,
                    )
                    await session.commit()

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

            return cast(WorkflowState, current_dict)