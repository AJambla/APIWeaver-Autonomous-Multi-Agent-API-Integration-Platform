"""Unit and integration tests for LangGraph-native APIWeaver pipeline."""

from __future__ import annotations

import uuid

import pytest

from app.models.enums import WorkflowStatus
from app.workflows.langgraph_pipeline import (
    LangGraphOrchestrator,
    create_apiweaver_graph,
    route_after_planner,
    route_after_testing,
)
from app.workflows.state import WorkflowState


def test_graph_compilation():
    """Verify that the LangGraph StateGraph builds and compiles cleanly."""
    builder = create_apiweaver_graph()
    graph = builder.compile()

    # Verify key nodes are registered in the graph
    node_names = set(graph.nodes.keys())
    assert "doc_agent" in node_names
    assert "planner_agent" in node_names
    assert "approval_gate" in node_names
    assert "code_agent" in node_names
    assert "test_agent" in node_names
    assert "repair_agent" in node_names
    assert "export_agent" in node_names
    assert "finalize" in node_names


def test_workflow_state_channels_preserved():
    """Verify channels like environment, spec_persisted, endpoints_discovered are declared and preserved."""
    builder = create_apiweaver_graph()
    graph = builder.compile()
    channels = set(graph.channels.keys())
    assert "environment" in channels
    assert "spec_persisted" in channels
    assert "endpoints_discovered" in channels
    assert "github_repo_name" in channels
    assert "errors" in channels


def test_workflow_state_errors_reducer():
    """Verify that add_errors appends errors without duplicates."""
    from app.workflows.state import add_errors

    assert add_errors(None, ["err1"]) == ["err1"]
    assert add_errors(["err1"], ["err2"]) == ["err1", "err2"]
    assert add_errors(["err1"], ["err1", "err2"]) == ["err1", "err2"]
    assert add_errors(["err1"], None) == ["err1"]


def test_route_after_planner():
    """Test routing decisions after the planning stage."""
    # 1. Plan only -> finalize
    assert route_after_planner({"stages": ["plan"]}) == "finalize"

    # 2. Plan + Generate, but not yet approved -> approval gate
    assert route_after_planner({"stages": ["plan", "generate"], "plan_approved": False}) == "approval_gate"
    assert route_after_planner({"stages": ["plan", "generate"]}) == "approval_gate"

    # 3. Plan + Generate, already approved -> code generation
    assert route_after_planner({"stages": ["plan", "generate"], "plan_approved": True}) == "code_agent"


def test_route_after_testing():
    """Test routing decisions after the testing stage."""
    # 1. All tests passed -> export
    passed_state: WorkflowState = {
        "stages": ["plan", "generate", "test", "export"],
        "test_run_summary": {"passed": 5, "failed": 0},
    }
    assert route_after_testing(passed_state) == "export_agent"

    # 2. Tests failed, attempts < 3 -> repair cycle
    failing_state_1: WorkflowState = {
        "stages": ["plan", "generate", "test", "export"],
        "test_run_summary": {"passed": 4, "failed": 1},
        "repair_attempts": [],
    }
    assert route_after_testing(failing_state_1) == "repair_agent"

    # 3. Tests failed, attempts >= 3 -> escalate to human gate
    failing_state_3: WorkflowState = {
        "stages": ["plan", "generate", "test", "export"],
        "test_run_summary": {"passed": 4, "failed": 1},
        "repair_attempts": [{}, {}, {}],
    }
    assert route_after_testing(failing_state_3) == "approval_gate"


@pytest.mark.asyncio
async def test_langgraph_orchestrator_plan_only(monkeypatch):
    """Test running LangGraphOrchestrator for doc + plan stages."""
    from app.workflows.llm import LLMClient

    async def _mock_generate_json(self, *, system_prompt: str, user_prompt: str, **kwargs):
        if "Doc" in system_prompt or "Documentation" in system_prompt:
            return {
                "title": "Users API",
                "base_url": "https://api.example.com",
                "confidence_score": 0.95,
                "endpoints": [
                    {"method": "GET", "path": "/users", "summary": "List users"},
                    {"method": "POST", "path": "/users", "summary": "Create user"},
                ],
            }, 50
        return {
            "phases": [{"phase_number": 1, "name": "Users", "endpoints": ["GET /users"]}],
            "dependency_graph": {"nodes": [], "edges": []},
        }, 50

    monkeypatch.setattr(LLMClient, "generate_json", _mock_generate_json)

    orchestrator = LangGraphOrchestrator()
    run_id = uuid.uuid4()

    sample_doc = b"# Users API\nGET /users - List users\nPOST /users - Create user"
    initial_state: WorkflowState = {
        "project_id": str(uuid.uuid4()),
        "organization_id": str(uuid.uuid4()),
        "document_filename": "users.md",
        "raw_document_bytes": sample_doc,
        "stages": ["plan"],
    }

    result = await orchestrator.run(run_id, initial_state)

    assert result["status"] == WorkflowStatus.COMPLETED
    assert result.get("normalized_spec") is not None
    assert result.get("execution_plan") is not None
    assert result.get("progress_percent") == 100


@pytest.mark.asyncio
async def test_langgraph_orchestrator_pauses_for_approval(monkeypatch):
    """Test that LangGraph pauses at the approval gate when plan is unapproved."""
    from app.workflows.llm import LLMClient

    async def _mock_generate_json(self, *, system_prompt: str, user_prompt: str, **kwargs):
        if "Doc" in system_prompt or "Documentation" in system_prompt:
            return {
                "title": "Users API",
                "base_url": "https://api.example.com",
                "confidence_score": 0.95,
                "endpoints": [
                    {"method": "GET", "path": "/users", "summary": "List users"},
                ],
            }, 50
        return {
            "phases": [{"phase_number": 1, "name": "Users", "endpoints": ["GET /users"]}],
            "dependency_graph": {"nodes": [], "edges": []},
        }, 50

    monkeypatch.setattr(LLMClient, "generate_json", _mock_generate_json)

    orchestrator = LangGraphOrchestrator()
    run_id = uuid.uuid4()

    sample_doc = b"# Users API\nGET /users - List users"
    initial_state: WorkflowState = {
        "project_id": str(uuid.uuid4()),
        "organization_id": str(uuid.uuid4()),
        "document_filename": "users.md",
        "raw_document_bytes": sample_doc,
        "stages": ["plan", "generate"],
        "plan_approved": False,
    }

    result = await orchestrator.run(run_id, initial_state)

    assert result["status"] == WorkflowStatus.PAUSED_FOR_APPROVAL
    assert result.get("current_node") == "completed"
    assert result.get("execution_plan") is not None
    assert not result.get("generated_files")


@pytest.mark.asyncio
async def test_cancelled_run_costs_and_metrics(session_factory, db) -> None:
    """Cancelled runs must compute estimated_cost_usd and persist UsageMetric."""
    from sqlalchemy import select

    from app.models.metrics import UsageMetric
    from app.models.organization import Organization
    from app.models.project import Project
    from app.models.workflow import WorkflowRun
    from app.workflows.langgraph_pipeline import WorkflowCancelledError

    org_id = uuid.uuid4()
    proj_id = uuid.uuid4()
    run_id = uuid.uuid4()

    async with db as session:
        org = Organization(id=org_id, name="Cost Org", slug=f"cost-org-{uuid.uuid4().hex[:6]}")
        proj = Project(id=proj_id, name="Cost Proj", organization_id=org_id)
        run = WorkflowRun(id=run_id, project_id=proj_id, status=WorkflowStatus.RUNNING)
        session.add_all([org, proj, run])
        await session.commit()

    orchestrator = LangGraphOrchestrator(session_factory=session_factory)

    # State with tokens used before cancellation
    initial_state: WorkflowState = {
        "project_id": str(proj_id),
        "organization_id": str(org_id),
        "workflow_run_id": str(run_id),
        "total_tokens_used": 5000,
        "stages": ["plan"],
    }

    # Simulate cancellation being raised during execution
    async def _cancelling_app(*args, **kwargs):
        raise WorkflowCancelledError("Cancelled by user")

    orchestrator.graph.ainvoke = _cancelling_app

    res = await orchestrator.run(run_id, initial_state)
    assert res["status"] == WorkflowStatus.CANCELLED

    async with db as session:
        refreshed_run = await session.get(WorkflowRun, run_id)
        assert refreshed_run.status == WorkflowStatus.CANCELLED
        assert refreshed_run.total_tokens_used == 5000
        assert refreshed_run.estimated_cost_usd > 0

        metric = await session.scalar(
            select(UsageMetric).where(
                UsageMetric.organization_id == org_id,
                UsageMetric.metric_name == "token_cost_usd",
            )
        )
        assert metric is not None
        assert metric.value == refreshed_run.estimated_cost_usd


@pytest.mark.asyncio
async def test_finalize_node_preserves_testing_status_on_approval_pause(session_factory, db) -> None:
    """A workflow paused for approval after testing must preserve ProjectStatus.TESTING, not revert to PLANNING."""
    from app.models.enums import ProjectStatus, WorkflowStatus
    from app.models.organization import Organization
    from app.models.project import Project
    from app.models.workflow import WorkflowRun
    from app.workflows.langgraph_pipeline import LangGraphOrchestrator

    org_id = uuid.uuid4()
    proj_id = uuid.uuid4()
    run_id = uuid.uuid4()

    async with db as session:
        org = Organization(id=org_id, name="Test Org", slug=f"test-org-{uuid.uuid4().hex[:6]}")
        proj = Project(id=proj_id, name="Test Proj", organization_id=org_id, status=ProjectStatus.TESTING)
        run = WorkflowRun(id=run_id, project_id=proj_id, status=WorkflowStatus.RUNNING)
        session.add_all([org, proj, run])
        await session.commit()

    orchestrator = LangGraphOrchestrator(session_factory=session_factory)
    state: WorkflowState = {
        "project_id": str(proj_id),
        "organization_id": str(org_id),
        "workflow_run_id": str(run_id),
        "status": WorkflowStatus.PAUSED_FOR_APPROVAL,
        "progress_percent": 80,
        "test_run_summary": {"failed": 2, "passed": 5},
        "repair_attempts": [{"attempt": 1}, {"attempt": 2}, {"attempt": 3}],
        "stages": [],
    }

    # Execute graph up to finalize
    graph = orchestrator.graph
    res = await graph.ainvoke(state, config={"configurable": {"thread_id": str(run_id)}})

    assert res["status"] == WorkflowStatus.PAUSED_FOR_APPROVAL
    assert res["progress_percent"] == 80

    async with db as session:
        refreshed_proj = await session.get(Project, proj_id)
        assert refreshed_proj.status == ProjectStatus.TESTING


@pytest.mark.asyncio
async def test_finalize_node_preserves_building_status_on_approval_pause(session_factory, db) -> None:
    """A workflow paused for approval with generated files must preserve ProjectStatus.BUILDING, not revert to PLANNING."""
    from app.models.enums import ProjectStatus, WorkflowStatus
    from app.models.organization import Organization
    from app.models.project import Project
    from app.models.workflow import WorkflowRun
    from app.workflows.langgraph_pipeline import LangGraphOrchestrator

    org_id = uuid.uuid4()
    proj_id = uuid.uuid4()
    run_id = uuid.uuid4()

    async with db as session:
        org = Organization(id=org_id, name="Build Org", slug=f"build-org-{uuid.uuid4().hex[:6]}")
        proj = Project(id=proj_id, name="Build Proj", organization_id=org_id, status=ProjectStatus.BUILDING)
        run = WorkflowRun(id=run_id, project_id=proj_id, status=WorkflowStatus.RUNNING)
        session.add_all([org, proj, run])
        await session.commit()

    orchestrator = LangGraphOrchestrator(session_factory=session_factory)
    state: WorkflowState = {
        "project_id": str(proj_id),
        "organization_id": str(org_id),
        "workflow_run_id": str(run_id),
        "status": WorkflowStatus.PAUSED_FOR_APPROVAL,
        "progress_percent": 60,
        "generated_files": [{"file_path": "client.py", "language": "python"}],
        "stages": [],
    }

    graph = orchestrator.graph
    res = await graph.ainvoke(state, config={"configurable": {"thread_id": str(run_id)}})

    assert res["status"] == WorkflowStatus.PAUSED_FOR_APPROVAL
    assert res["progress_percent"] == 60

    async with db as session:
        refreshed_proj = await session.get(Project, proj_id)
        assert refreshed_proj.status == ProjectStatus.BUILDING

