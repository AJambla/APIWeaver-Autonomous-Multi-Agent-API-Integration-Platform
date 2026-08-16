"""Tests for Testing Agent and API (`Feature.md §13-14`)."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.workflows.agents.test_agent import run_test_agent, MockSandboxClient, FailureClassifier, generate_test_fixtures
from app.workflows.state import WorkflowState


class TestTestingAgent:
    """Unit tests for the Testing Agent."""

    @pytest.fixture
    def mock_state(self) -> WorkflowState:
        return WorkflowState(
            project_id="test-project",
            organization_id="test-org",
            workflow_run_id="test-run",
            stages=["test"],
            target_languages=["python"],
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
            generated_files=[
                {
                    "file_path": "client.py",
                    "content_s3_key": "generated/test-project/client.py",
                    "language": "python",
                    "file_type": "sdk",
                }
            ],
            test_suite=[],
            errors=[],
            total_tokens_used=0,
            status="running",
            progress_percent=0,
            current_node="",
        )

    @pytest.mark.asyncio
    async def test_generate_test_fixtures(self):
        """Test test fixture generation."""
        with patch("app.workflows.agents.test_agent.LLMClient") as mock_llm:
            mock_client = AsyncMock()
            mock_client.generate_json.return_value = (
                {
                    "request": {"params": {"limit": 10}, "body": None},
                    "expected_status": 200,
                    "expected_response_shape": {"type": "array"},
                },
                50,
            )
            mock_llm.return_value = mock_client

            spec = {
                "endpoints": [
                    {
                        "method": "GET",
                        "path": "/users",
                        "operationId": "listUsers",
                        "parameters": [{"name": "limit", "location": "query", "type": "integer", "required": False}],
                        "request_schema": None,
                        "response_schemas": {"200": {"type": "array"}},
                    }
                ]
            }

            fixtures = await generate_test_fixtures(spec)

            assert "GET /users" in fixtures
            assert fixtures["GET /users"]["expected_status"] == 200

    @pytest.mark.asyncio
    async def test_failure_classification(self):
        """Test failure classification."""
        with patch("app.workflows.agents.test_agent.LLMClient") as mock_llm:
            mock_client = AsyncMock()
            mock_client.generate_json.return_value = (
                {
                    "classification": "schema_mismatch",
                    "confidence": 0.9,
                    "reasoning": "Response does not match expected schema",
                },
                50,
            )
            mock_llm.return_value = mock_client

            classifier = FailureClassifier()
            result = await classifier.classify(
                {"status_code": 500, "response_snapshot": {"body": "Internal Server Error"}},
                {"method": "GET", "path": "/users"},
                [],
            )

            assert result["classification"] == "schema_mismatch"
            assert result["confidence"] == 0.9

    @pytest.mark.asyncio
    async def test_run_test_agent(self, mock_state):
        """Test full testing agent execution."""
        with patch("app.workflows.agents.test_agent.LLMClient") as mock_llm:
            mock_client = AsyncMock()
            # Mock fixture generation
            mock_client.generate_json.side_effect = [
                # generate_test_fixtures
                ({"request": {"params": {}, "body": None}, "expected_status": 200, "expected_response_shape": {}}, 50),
                # Failure classification (if needed)
            ]
            mock_llm.return_value = mock_client

            # Mock storage_service to avoid S3 calls
            with patch("app.workflows.agents.test_agent.storage_service") as mock_storage:
                mock_storage.download = AsyncMock(return_value=b"""
from pydantic import BaseModel
class User(BaseModel):
    pass
""")

                result = await run_test_agent(mock_state)

                assert result["status"] in ("completed", "completed_with_failures")
                assert "test_suite" in result
                assert "test_run_summary" in result


class TestTestingAPI:
    """Integration tests for the Testing API."""

    @pytest.mark.asyncio
    async def test_trigger_test_endpoint(self, client, auth_headers):
        """Test POST /projects/{id}/test endpoint."""
        pass

    @pytest.mark.asyncio
    async def test_get_test_run_endpoint(self, client, auth_headers):
        """Test GET /projects/{id}/test-runs/{run_id} endpoint."""
        pass

    @pytest.mark.asyncio
    async def test_list_repairs_endpoint(self, client, auth_headers):
        """Test GET /projects/{id}/test-runs/{run_id}/repairs endpoint."""
        pass