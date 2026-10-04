"""Tests for Testing Agent and API (`Feature.md §13-14`)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.workflows.agents.test_agent import (
    FailureClassifier,
    generate_test_fixtures,
    run_test_agent,
)
from app.workflows.state import WorkflowState
from tests.conftest import TEST_PASSWORD


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

    async def _register_with_project(self, client, tag: str) -> tuple[dict[str, str], str]:
        """Register a fresh user/org plus one project; returns (headers, project_id)."""
        res = await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"h3-{tag}-{uuid.uuid4().hex[:8]}@example.com",
                "password": TEST_PASSWORD,
                "full_name": f"H3 {tag}",
                "organization_name": f"H3 Org {tag} {uuid.uuid4().hex[:6]}",
            },
        )
        assert res.status_code == 201, res.text
        headers = {"Authorization": f"Bearer {res.json()['access_token']}"}
        me = await client.get("/api/v1/auth/me", headers=headers)
        org_id = me.json()["organizations"][0]["organization_id"]
        proj = await client.post(
            "/api/v1/projects",
            json={"name": f"H3 Project {tag}", "organization_id": org_id},
            headers=headers,
        )
        assert proj.status_code == 201, proj.text
        return headers, proj.json()["id"]

    @pytest.mark.asyncio
    async def test_trigger_test_ignores_query_project_id(self, client, db):
        """The test run must target the authorized path {id}, never a caller-supplied
        `project_id` query param (audit finding H3, IDOR)."""
        from app.models.testing import TestRun

        headers_a, project_a = await self._register_with_project(client, "a")
        _, project_b = await self._register_with_project(client, "b")

        res = await client.post(
            f"/api/v1/projects/{project_a}/test",
            params={"project_id": project_b},
            json={"environment": "sandbox"},
            headers=headers_a,
        )
        assert res.status_code == 202, res.text

        async with db as session:
            run = await session.get(TestRun, uuid.UUID(res.json()["test_run_id"]))
            assert run is not None
            assert str(run.project_id) == project_a
            foreign = list((await session.execute(
                select(TestRun).where(TestRun.project_id == uuid.UUID(project_b))
            )).scalars())
            assert foreign == []

    @pytest.mark.asyncio
    async def test_get_test_run_endpoint(self, client, auth_headers):
        """Test GET /projects/{id}/test-runs/{run_id} endpoint."""
        pass

    @pytest.mark.asyncio
    async def test_list_repairs_endpoint(self, client, auth_headers):
        """Test GET /projects/{id}/test-runs/{run_id}/repairs endpoint."""
        pass