"""Tests for Code Generator Agent and API (`Feature.md §7-12`)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

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