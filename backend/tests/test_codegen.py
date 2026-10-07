"""Tests for Code Generator Agent and API (`Feature.md §7-12`)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.codegen import CodeGenerationRun, GeneratedFile
from app.models.enums import OrgRole, ProjectRole
from app.models.workflow import WorkflowRun
from app.workflows.agents.code_agent import run_code_agent
from app.workflows.state import WorkflowState
from tests.conftest import TEST_PASSWORD


class TestCodeGeneratorAgent:
    """Unit tests for the Code Generator Agent."""

    @pytest.fixture
    def mock_state(self) -> WorkflowState:
        return WorkflowState(
            project_id="test-project",
            organization_id="test-org",
            workflow_run_id="test-run",
            stages=["generate"],
            target_languages=["python", "node"],
            normalized_spec={
                "title": "Test API",
                "base_url": "https://api.example.com/v1",
                "endpoints": [
                    {
                        "method": "GET",
                        "path": "/users",
                        "summary": "List users",
                        "operationId": "listUsers",
                        "parameters": [
                            {"name": "limit", "location": "query", "type": "integer", "required": False}
                        ],
                        "request_schema": None,
                        "response_schemas": {
                            "200": {"type": "array", "items": {"type": "object"}}
                        },
                    }
                ],
            },
            execution_plan={
                "phases": [
                    {
                        "phase_number": 1,
                        "name": "Users",
                        "endpoints": ["GET /users"],
                    }
                ]
            },
            plan_approved=True,
            generated_files=[],
            test_suite=[],
            errors=[],
            total_tokens_used=0,
            status="running",
            progress_percent=0,
            current_node="",
        )

    @pytest.mark.asyncio
    async def test_run_code_agent_python(self, mock_state):
        """Test code generation for Python target."""
        with patch("app.workflows.agents.code_agent.LLMClient") as mock_llm, \
             patch("app.workflows.agents.code_agent.storage_service") as mock_storage:
            mock_storage.upload = AsyncMock()
            mock_storage.download = AsyncMock(return_value=b"content")
            mock_client = AsyncMock()
            mock_client.generate_json.return_value = (
                {
                    "models.py": "from pydantic import BaseModel\n\nclass User(BaseModel):\n    pass\n",
                    "client.py": "import httpx\n\nclass Client:\n    pass\n",
                },
                100,
            )
            mock_llm.return_value = mock_client

            result = await run_code_agent(mock_state, phase_number=1)

            assert result["status"] == "generated"
            assert len(result["generated_files"]) > 0
            python_files = [f for f in result["generated_files"] if f["language"] == "python"]
            assert len(python_files) > 0

    @pytest.mark.asyncio
    async def test_run_code_agent_node(self, mock_state):
        """Test code generation for Node.js target."""
        mock_state["target_languages"] = ["node"]

        with patch("app.workflows.agents.code_agent.LLMClient") as mock_llm, \
             patch("app.workflows.agents.code_agent.storage_service") as mock_storage:
            mock_storage.upload = AsyncMock()
            mock_storage.download = AsyncMock(return_value=b"content")
            mock_client = AsyncMock()
            mock_client.generate_json.return_value = (
                {
                    "types.ts": "import { z } from \"zod\";\n\nexport const UserSchema = z.object({});",
                    "client.ts": "export class Client {}\n",
                },
                100,
            )
            mock_llm.return_value = mock_client

            result = await run_code_agent(mock_state, phase_number=1)

            assert result["status"] == "generated"
            node_files = [f for f in result["generated_files"] if f["language"] == "node"]
            assert len(node_files) > 0


class TestCodeGeneratorAPI:
    """Integration tests for the Code Generation API."""

    async def _register_with_project(self, client: AsyncClient, tag: str) -> tuple[dict[str, str], str]:
        """Register a fresh user/org and create one project; returns (headers, project_id)."""
        res = await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"h1-{tag}-{uuid.uuid4().hex[:8]}@example.com",
                "password": TEST_PASSWORD,
                "full_name": f"H1 {tag}",
                "organization_name": f"H1 Org {tag} {uuid.uuid4().hex[:6]}",
            },
        )
        assert res.status_code == 201, res.text
        headers = {"Authorization": f"Bearer {res.json()['access_token']}"}
        me = await client.get("/api/v1/auth/me", headers=headers)
        org_id = me.json()["organizations"][0]["organization_id"]
        proj = await client.post(
            "/api/v1/projects",
            json={"name": f"H1 Project {tag}", "organization_id": org_id},
            headers=headers,
        )
        assert proj.status_code == 201, proj.text
        return headers, proj.json()["id"]

    @pytest.mark.asyncio
    async def test_trigger_generate_ignores_query_project_id(self, client, db):
        """Authorization targets the path {id}; a `project_id` query param must not
        redirect the run onto a foreign project (audit finding H1, IDOR)."""
        headers_a, project_a = await self._register_with_project(client, "a")
        _, project_b = await self._register_with_project(client, "b")

        res = await client.post(
            f"/api/v1/projects/{project_a}/generate",
            params={"project_id": project_b},
            json={"stages": ["plan"]},
            headers=headers_a,
        )
        assert res.status_code == 202, res.text
        run_id = res.json()["workflow_run_id"]

        async with db as session:
            run = await session.get(WorkflowRun, uuid.UUID(run_id))
            assert run is not None
            assert str(run.project_id) == project_a
            foreign = list((await session.execute(
                select(WorkflowRun).where(WorkflowRun.project_id == uuid.UUID(project_b))
            )).scalars())
            assert foreign == []

    async def _seed_generated_file(
        self, session, project_id: uuid.UUID, file_path: str
    ) -> uuid.UUID:
        run = WorkflowRun(project_id=project_id, status="completed")
        session.add(run)
        await session.flush()
        code_run = CodeGenerationRun(
            workflow_run_id=run.id, target_language="python", status="completed"
        )
        session.add(code_run)
        await session.flush()
        gen_file = GeneratedFile(
            code_generation_run_id=code_run.id,
            file_path=file_path,
            content_s3_key=f"generated/{project_id}/{file_path}",
            language="python",
            file_type="sdk",
        )
        session.add(gen_file)
        await session.flush()
        return gen_file.id

    @pytest.mark.asyncio
    async def test_list_files_ignores_query_project_id(self, client, db):
        """A viewer of one project cannot list another project's files by overriding
        `project_id` on the query string (audit finding H2, IDOR)."""
        from tests.conftest import (
            add_org_member,
            add_project_member,
            make_org,
            make_project,
            make_user,
        )

        async with db as session:
            org = await make_org(session, name=f"H2 Org {uuid.uuid4().hex[:6]}")
            reader = await make_user(session, email=f"h2-reader-{uuid.uuid4().hex[:8]}@example.com")
            await add_org_member(session, org=org, user=reader, role=OrgRole.MEMBER)
            project_a = await make_project(session, org=org, name="H2 Project A")
            project_b = await make_project(session, org=org, name="H2 Project B")
            await add_project_member(
                session, project=project_a, user=reader, role=ProjectRole.VIEWER
            )
            file_a = await self._seed_generated_file(session, project_a.id, "a_only.py")
            await self._seed_generated_file(session, project_b.id, "b_secret.py")
            await session.commit()

        login = await client.post(
            "/api/v1/auth/login",
            json={"email": reader.email, "password": TEST_PASSWORD},
        )
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        res = await client.get(
            f"/api/v1/projects/{project_a.id}/files",
            params={"project_id": str(project_b.id)},
            headers=headers,
        )
        assert res.status_code == 200, res.text
        paths = [row["file_path"] for row in res.json()]
        assert paths == ["a_only.py"]
        assert all(row["id"] == str(file_a) for row in res.json())

    @pytest.mark.asyncio
    async def test_file_content_is_scoped_to_owning_project(self, client, db):
        """File content is looked up through its project, so another tenant's file id is
        a 404 rather than a download (audit finding H2, IDOR)."""
        from unittest.mock import AsyncMock

        from tests.conftest import add_org_member, make_org, make_project, make_user

        async with db as session:
            caller_org = await make_org(session, name=f"H2 Caller {uuid.uuid4().hex[:6]}")
            caller = await make_user(session, email=f"h2-caller-{uuid.uuid4().hex[:8]}@example.com")
            await add_org_member(session, org=caller_org, user=caller, role=OrgRole.OWNER)
            own_project = await make_project(session, org=caller_org, name="H2 Own Project")
            own_file = await self._seed_generated_file(session, own_project.id, "mine.py")

            victim_org = await make_org(session, name=f"H2 Victim {uuid.uuid4().hex[:6]}")
            victim = await make_user(session, email=f"h2-victim-{uuid.uuid4().hex[:8]}@example.com")
            await add_org_member(session, org=victim_org, user=victim, role=OrgRole.OWNER)
            victim_project = await make_project(session, org=victim_org, name="H2 Victim Project")
            foreign_file = await self._seed_generated_file(session, victim_project.id, "theirs.py")
            await session.commit()

        login = await client.post(
            "/api/v1/auth/login",
            json={"email": caller.email, "password": TEST_PASSWORD},
        )
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        fake_storage = SimpleNamespace(download=AsyncMock(return_value=b"secret bytes"))
        with patch("app.services.storage_service.storage_service", fake_storage):
            leaked = await client.get(
                f"/api/v1/projects/{own_project.id}/files/{foreign_file}/content",
                headers=headers,
            )
            assert leaked.status_code == 404
            fake_storage.download.assert_not_awaited()

            own = await client.get(
                f"/api/v1/projects/{own_project.id}/files/{own_file}/content",
                headers=headers,
            )
            assert own.status_code == 200, own.text
            assert own.json()["file_path"] == "mine.py"
            assert own.json()["content"] == "secret bytes"

    def test_merge_python_code_preserves_methods(self):
        """Verify _merge_python_code accumulates methods from multiple phases."""
        from app.workflows.agents.code_agent import _merge_python_code

        phase1_code = (
            "import httpx\n\n"
            "class Client:\n"
            "    def __init__(self, base_url: str | None = None) -> None:\n"
            "        self.base_url = base_url\n\n"
            "    async def list_pets(self) -> httpx.Response:\n"
            "        return await self._request('GET', '/pets')\n"
        )
        phase2_code = (
            "import pydantic\n\n"
            "class Pet(pydantic.BaseModel):\n"
            "    name: str\n\n"
            "class Client:\n"
            "    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:\n"
            "        self.base_url = base_url\n"
            "        self.api_key = api_key\n\n"
            "    async def create_pet(self, data: dict) -> httpx.Response:\n"
            "        return await self._request('POST', '/pets', json=data)\n"
        )
        merged = _merge_python_code(phase1_code, phase2_code)
        assert "async def list_pets" in merged
        assert "async def create_pet" in merged
        assert "class Pet" in merged
        assert "import httpx" in merged
        assert "import pydantic" in merged