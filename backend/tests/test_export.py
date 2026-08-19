"""Tests for Export Agent and API (`Feature.md §15-24`)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workflows.agents.export_agent import ExportAgent
from app.workflows.state import WorkflowState


class TestExportAgent:
    """Unit tests for the Export Agent."""

    @pytest.fixture
    def mock_state(self) -> WorkflowState:
        return WorkflowState(
            project_id="test-project",
            organization_id="test-org",
            workflow_run_id="test-run",
            stages=["export"],
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
                    },
                    {
                        "method": "POST",
                        "path": "/users",
                        "summary": "Create user",
                        "operationId": "createUser",
                        "parameters": [],
                        "request_schema": {"type": "object", "properties": {"name": {"type": "string"}}},
                        "response_schemas": {"201": {"type": "object"}},
                    }
                ],
            },
            execution_plan={
                "phases": [
                    {
                        "phase_number": 1,
                        "name": "Users",
                        "endpoints": ["GET /users", "POST /users"],
                    }
                ]
            },
            plan_approved=True,
            generated_files=[
                {
                    "file_path": "client.py",
                    "content_s3_key": "generated/test-project/client.py",
                    "language": "python",
                    "file_type": "sdk",
                },
                {
                    "file_path": "client.ts",
                    "content_s3_key": "generated/test-project/client.ts",
                    "language": "node",
                    "file_type": "sdk",
                }
            ],
            test_suite=[
                {"endpoint_id": "1", "method": "GET", "path": "/users", "status": "passed", "status_code": 200},
                {"endpoint_id": "2", "method": "POST", "path": "/users", "status": "passed", "status_code": 201},
            ],
            test_run_summary={"total": 2, "passed": 2, "failed": 0, "skipped": 0, "pass_rate": 1.0},
            errors=[],
            total_tokens_used=0,
            status="running",
            progress_percent=0,
            current_node="",
        )

    @pytest.mark.asyncio
    async def test_package_sdk(self, mock_state):
        """Test SDK packaging."""
        with patch("app.workflows.agents.export_agent.storage_service") as mock_storage:
            mock_storage.download = AsyncMock(return_value=b"# test content")
            mock_storage.upload = AsyncMock()

            agent = ExportAgent()
            result = await agent._package_sdk(
                project_id="test-project",
                generated_files=mock_state["generated_files"],
                test_run_summary=mock_state["test_run_summary"],
                target_languages=mock_state["target_languages"],
                normalized_spec=mock_state["normalized_spec"],
            )

            assert result["type"] == "sdk"
            assert len(result["artifacts"]) == 2  # python + node

    @pytest.mark.asyncio
    async def test_package_client(self, mock_state):
        """Test client packaging."""
        with patch("app.workflows.agents.export_agent.storage_service") as mock_storage:
            mock_storage.download = AsyncMock(return_value=b"# test content")
            mock_storage.upload = AsyncMock()

            agent = ExportAgent()
            result = await agent._package_client(
                project_id="test-project",
                generated_files=mock_state["generated_files"],
                normalized_spec=mock_state["normalized_spec"],
            )

            assert result["type"] == "client"
            assert len(result["artifacts"]) == 2  # python + node

    @pytest.mark.asyncio
    async def test_package_docker(self, mock_state):
        """Test Docker packaging."""
        with patch("app.workflows.agents.export_agent.storage_service") as mock_storage:
            mock_storage.upload = AsyncMock()

            agent = ExportAgent()
            result = await agent._package_docker(
                project_id="test-project",
                target_languages=mock_state["target_languages"],
                normalized_spec=mock_state["normalized_spec"],
            )

            assert result["type"] == "docker"
            assert len(result["artifacts"]) == 2  # Dockerfile + docker-compose.yml

    @pytest.mark.asyncio
    async def test_package_mcp(self, mock_state):
        """Test MCP packaging."""
        with patch("app.workflows.agents.export_agent.storage_service") as mock_storage:
            mock_storage.upload = AsyncMock()

            agent = ExportAgent()
            result = await agent._package_mcp(
                project_id="test-project",
                normalized_spec=mock_state["normalized_spec"],
            )

            assert result["type"] == "mcp"
            assert result["tools_generated"] == 2
            assert "artifacts" in result

    @pytest.mark.asyncio
    async def test_package_docs(self, mock_state):
        """Test docs packaging."""
        with patch("app.workflows.agents.export_agent.storage_service") as mock_storage:
            mock_storage.upload = AsyncMock()

            agent = ExportAgent()
            result = await agent._package_docs(
                project_id="test-project",
                normalized_spec=mock_state["normalized_spec"],
            )

            assert result["type"] == "docs"
            assert len(result["artifacts"]) == 2  # openapi.json + reference.md

    @pytest.mark.asyncio
    async def test_package_cicd(self, mock_state):
        """Test CI/CD packaging."""
        with patch("app.workflows.agents.export_agent.storage_service") as mock_storage:
            mock_storage.upload = AsyncMock()

            agent = ExportAgent()
            result = await agent._package_cicd(
                project_id="test-project",
                target_languages=mock_state["target_languages"],
            )

            assert result["type"] == "cicd"
            assert len(result["artifacts"]) == 2  # python + node workflows

    @pytest.mark.asyncio
    async def test_run_full_export(self, mock_state):
        """Test full export pipeline."""
        with patch("app.workflows.agents.export_agent.storage_service") as mock_storage:
            mock_storage.download = AsyncMock(return_value=b"# test content")
            mock_storage.upload = AsyncMock()

            agent = ExportAgent()
            result = await agent.run(mock_state, export_types=["sdk", "client", "docker", "mcp", "docs", "cicd"])

            assert result["status"] in ("completed", "completed_with_errors")
            assert "exports" in result
            assert len(result["exports"]) == 6


class TestExportAPI:
    """Integration tests for the Export API."""

    @pytest.mark.asyncio
    async def test_trigger_export_endpoint(self, client, auth_headers):
        """Test POST /projects/{id}/export endpoint."""
        pass

    @pytest.mark.asyncio
    async def test_export_mcp_endpoint(self, client, auth_headers):
        """Test POST /projects/{id}/export/mcp endpoint."""
        pass