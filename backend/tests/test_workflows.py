"""Tests for Workflow API and LangGraph Orchestrator (Phase 2)."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.enums import WorkflowStatus
from app.models.workflow import WorkflowRun
from app.workflows.agents.doc_agent import run_doc_agent
from app.workflows.agents.planner_agent import run_planner_agent
from app.workflows.state import WorkflowState
from tests.conftest import TEST_PASSWORD


async def _setup_project(client: AsyncClient) -> tuple[str, str, dict[str, str]]:
    """Helper to register user and create a project."""
    res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "workflow_user@example.com",
            "password": TEST_PASSWORD,
            "full_name": "Workflow Tester",
            "organization_name": "Workflow Org",
        },
    )
    assert res.status_code == 201
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    me = await client.get("/api/v1/auth/me", headers=headers)
    org_id = me.json()["organizations"][0]["organization_id"]

    proj = await client.post(
        "/api/v1/projects",
        json={"name": "Orchestrator Test Project", "organization_id": org_id},
        headers=headers,
    )
    assert proj.status_code == 201
    return proj.json()["id"], org_id, headers


async def test_trigger_workflow_creates_run(client: AsyncClient) -> None:
    project_id, _, headers = await _setup_project(client)

    response = await client.post(
        f"/api/v1/projects/{project_id}/workflows",
        json={"stages": ["plan"], "target_languages": ["python"]},
        headers=headers,
    )
    assert response.status_code == 202
    data = response.json()
    assert data["workflow_run_id"]
    assert data["status"] == "queued"

    # Poll status
    run_id = data["workflow_run_id"]
    get_res = await client.get(f"/api/v1/workflows/{run_id}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["id"] == run_id


async def test_cancel_workflow(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    project_id, _, headers = await _setup_project(client)
    import uuid

    # Arrange a running workflow run in DB
    async with session_factory() as session:
        run = WorkflowRun(
            project_id=uuid.UUID(project_id),
            status=WorkflowStatus.RUNNING,
        )
        session.add(run)
        await session.commit()
        run_id = str(run.id)

    cancel_res = await client.post(f"/api/v1/workflows/{run_id}/cancel", headers=headers)
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == WorkflowStatus.CANCELLED


async def test_orchestrator_agent_nodes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Test Doc and Planner agent nodes in isolation."""
    sample_doc = b"# Pet API\nGET /pets - List all pets\nPOST /pets - Create a pet"
    state: WorkflowState = {
        "project_id": "test-proj",
        "organization_id": "test-org",
        "workflow_run_id": "test-run",
        "document_filename": "api.md",
        "raw_document_bytes": sample_doc,
        "stages": ["plan"],
    }

    # Run doc agent
    doc_out = await run_doc_agent(state)
    assert doc_out["status"] == "spec_ready"
    assert doc_out["normalized_spec"] is not None
    state.update(doc_out)  # type: ignore[arg-type]

    # Run planner agent
    planner_out = await run_planner_agent(state)
    assert planner_out["status"] == "plan_ready"
    assert planner_out["execution_plan"] is not None
