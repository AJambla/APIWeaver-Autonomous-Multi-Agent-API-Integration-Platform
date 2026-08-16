"""Tests for Code Generator Agent and API (`Feature.md §7-12`)."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.workflows.agents.code_agent import run_code_agent
from app.workflows.state import WorkflowState


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
        with patch("app.workflows.agents.code_agent.LLMClient") as mock_llm:
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

        with patch("app.workflows.agents.code_agent.LLMClient") as mock_llm:
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

    @pytest.mark.asyncio
    async def test_trigger_generate_endpoint(self, client, auth_headers):
        """Test POST /projects/{id}/generate endpoint."""
        # This would require a full setup with database
        # Skipping for now - would be implemented with proper test fixtures
        pass