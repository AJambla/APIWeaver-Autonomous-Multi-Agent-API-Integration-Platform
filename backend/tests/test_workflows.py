"""Tests for Workflow API and LangGraph Orchestrator (Phase 2)."""

from __future__ import annotations

import uuid

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

    # Run doc agent with qdrant_client=None for tests
    doc_out = await run_doc_agent(state, qdrant_client=None)
    assert doc_out["status"] == "spec_ready"
    assert doc_out["normalized_spec"] is not None
    state.update(doc_out)  # type: ignore[arg-type]

    # Run planner agent
    planner_out = await run_planner_agent(state)
    assert planner_out["status"] == "plan_ready"
    assert planner_out["execution_plan"] is not None


async def _seed_run_with_org_member(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    tag: str,
) -> tuple[dict[str, str], str, str, str]:
    """A running workflow run in a project the caller can only see, not act on.

    The principal holds the org role `member`, which grants nothing on a project
    (`enforce.py` resolve_project_role), so this is exactly the principal the old
    membership-only checks let through (audit M5).
    """
    from app.models.enums import OrgRole
    from tests.conftest import add_org_member, make_org, make_project, make_user

    async with session_factory() as session:
        org = await make_org(session, name=f"{tag} Org {uuid.uuid4().hex[:6]}")
        member = await make_user(session, email=f"{tag}-{uuid.uuid4().hex[:8]}@example.com")
        await add_org_member(session, org=org, user=member, role=OrgRole.MEMBER)
        project = await make_project(session, org=org, name=f"{tag} Project")
        run = WorkflowRun(project_id=project.id, status=WorkflowStatus.RUNNING)
        session.add(run)
        await session.flush()
        project_id, run_id, user_id, email = (
            str(project.id),
            str(run.id),
            str(member.id),
            member.email,
        )
        await session.commit()

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": TEST_PASSWORD},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    return headers, project_id, run_id, user_id


async def _grant_project_role(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: str,
    user_id: str,
    role: str,
) -> None:
    from app.models.project import Project
    from app.models.user import User
    from tests.conftest import add_project_member

    async with session_factory() as session:
        project = await session.get(Project, uuid.UUID(project_id))
        user = await session.get(User, uuid.UUID(user_id))
        assert project is not None and user is not None
        await add_project_member(session, project=project, user=user, role=role)
        await session.commit()


async def test_cancel_requires_project_editor(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`WORKFLOW_CANCEL` is in the matrix as editor+; cancel must enforce it (audit M5)."""
    from app.models.enums import ProjectRole

    headers, project_id, run_id, user_id = await _seed_run_with_org_member(
        client, session_factory, "m5cancel"
    )

    denied = await client.post(f"/api/v1/workflows/{run_id}/cancel", headers=headers)
    assert denied.status_code == 403, denied.text

    await _grant_project_role(session_factory, project_id, user_id, ProjectRole.EDITOR)
    allowed = await client.post(f"/api/v1/workflows/{run_id}/cancel", headers=headers)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["status"] == WorkflowStatus.CANCELLED


async def test_list_workflows_requires_project_viewer(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Any org member could enumerate another project's runs; the read gate is viewer."""
    from app.models.enums import ProjectRole

    headers, project_id, run_id, user_id = await _seed_run_with_org_member(
        client, session_factory, "m5list"
    )

    denied = await client.get(
        "/api/v1/workflows", params={"project_id": project_id}, headers=headers
    )
    assert denied.status_code == 403, denied.text

    await _grant_project_role(session_factory, project_id, user_id, ProjectRole.VIEWER)
    allowed = await client.get(
        "/api/v1/workflows", params={"project_id": project_id}, headers=headers
    )
    assert allowed.status_code == 200, allowed.text
    assert [row["id"] for row in allowed.json()] == [run_id]
