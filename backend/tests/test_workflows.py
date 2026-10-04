"""Tests for Workflow API and LangGraph Orchestrator (Phase 2)."""

from __future__ import annotations

import uuid
from typing import Any

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


async def _seed_project_run(
    session_factory: async_sessionmaker[AsyncSession], tag: str
) -> tuple[str, str]:
    """An org, project and RUNNING run row for orchestrator tests."""
    from tests.conftest import make_org, make_project

    async with session_factory() as session:
        org = await make_org(session, name=f"{tag} Org {uuid.uuid4().hex[:6]}")
        project = await make_project(session, org=org, name=f"{tag} Project")
        run = WorkflowRun(project_id=project.id, status=WorkflowStatus.RUNNING)
        session.add(run)
        await session.flush()
        project_id, run_id = str(project.id), str(run.id)
        await session.commit()
    return project_id, run_id


def _generate_state(project_id: str, run_id: str, *, phase_count: int, token_budget: int) -> Any:
    """A state parked at the approved-plan gate, ready for the generate stage."""
    return {
        "project_id": project_id,
        "workflow_run_id": run_id,
        "stages": ["generate"],
        "normalized_spec": {
            "title": "Budget API",
            "base_url": "https://api.example.com",
            "endpoints": [],
        },
        "execution_plan": {"phases": [{"phase_number": n} for n in range(1, phase_count + 1)]},
        "plan_approved": True,
        "generated_files": [],
        "token_budget": token_budget,
        "total_tokens_used": 0,
        "errors": [],
    }


def _spending_code_agent(calls: list[Any], spend: int):
    """Stand-in for `run_code_agent`: records the phase it was asked for and reports
    cumulative token usage the way the real agent does."""

    async def _run_code_agent(
        state: Any, phase_number: int | None = None, **_: Any
    ) -> dict[str, Any]:
        calls.append(phase_number)
        return {
            "total_tokens_used": state.get("total_tokens_used", 0) + spend,
            "generated_files": [{"file_path": f"phase_{phase_number}.py", "language": "python"}],
        }

    return _run_code_agent


async def test_generation_stops_before_a_phase_the_budget_cannot_pay_for(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Phase-level enforcement: before M13 the budget was only checked between stages,
    so every phase of an approved plan ran regardless of how much it had already spent."""
    from unittest.mock import patch

    from app.workflows.agents import code_agent as code_agent_module
    from app.workflows.orchestrator import Orchestrator

    project_id, run_id = await _seed_project_run(session_factory, "m13phases")
    calls: list[Any] = []
    state = _generate_state(project_id, run_id, phase_count=3, token_budget=1_000)

    with patch.object(code_agent_module, "run_code_agent", _spending_code_agent(calls, 600)):
        result = await Orchestrator(session_factory).run(uuid.UUID(run_id), state)

    assert calls == [1, 2]
    assert result["status"] == WorkflowStatus.FAILED
    assert any("token_budget_exceeded" in error for error in result["errors"])

    async with session_factory() as session:
        run_obj = await session.get(WorkflowRun, uuid.UUID(run_id))
        assert run_obj is not None
        assert run_obj.status == WorkflowStatus.FAILED


async def test_consistency_pass_respects_the_token_budget(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The cross-chunk consistency pass is a further LLM call, not part of the phase loop."""
    from unittest.mock import patch

    from app.workflows.agents import code_agent as code_agent_module
    from app.workflows.orchestrator import Orchestrator

    project_id, run_id = await _seed_project_run(session_factory, "m13consistency")
    calls: list[Any] = []
    state = _generate_state(project_id, run_id, phase_count=1, token_budget=1_000)

    with patch.object(code_agent_module, "run_code_agent", _spending_code_agent(calls, 1_200)):
        result = await Orchestrator(session_factory).run(uuid.UUID(run_id), state)

    assert calls == [1]
    assert result["status"] == WorkflowStatus.FAILED


class _FakeAsyncResult:
    def __init__(self, updates: dict[str, Any]) -> None:
        self._updates = updates

    def get(self, timeout: int | None = None) -> dict[str, Any]:
        return self._updates


class _FakeCeleryApp:
    """Records dispatched tasks and answers them the way the agent workers do."""

    def __init__(self, spend: int) -> None:
        self.dispatched: list[tuple[str, Any]] = []
        self._spend = spend

    def send_task(self, name: str, args: list[Any] | None = None, **_: Any) -> _FakeAsyncResult:
        self.dispatched.append((name, args))
        state = args[1] if args else {}
        return _FakeAsyncResult(
            {
                "total_tokens_used": state.get("total_tokens_used", 0) + self._spend,
                "generated_files": [{"file_path": "async_phase.py", "language": "python"}],
            }
        )


async def test_async_dispatch_enforces_the_token_budget(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The Celery dispatch path checked the budget nowhere, so async runs could spend
    without limit."""
    from unittest.mock import patch

    from agent_worker import celery_app as celery_module

    from app.workflows.orchestrator import Orchestrator

    project_id, run_id = await _seed_project_run(session_factory, "m13async")
    fake_celery = _FakeCeleryApp(spend=600)
    state = _generate_state(project_id, run_id, phase_count=3, token_budget=1_000)

    with patch.object(celery_module, "app", fake_celery):
        result = await Orchestrator(
            session_factory, execution_mode="async"
        ).run(uuid.UUID(run_id), state)

    dispatched_phases = [args[2] for _, args in fake_celery.dispatched]
    assert dispatched_phases == [1, 2]
    assert result["status"] == WorkflowStatus.FAILED
    assert any("token_budget_exceeded" in error for error in result["errors"])
