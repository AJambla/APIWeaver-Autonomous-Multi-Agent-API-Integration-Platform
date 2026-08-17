"""Tests for GitHub export functionality."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workflows.agents.export_agent import ExportAgent
from app.workflows.state import WorkflowState


class TestGitHubExport:
    """Tests for GitHub export packaging."""

    @pytest.fixture
    def mock_state(self) -> WorkflowState:
        return WorkflowState(
            project_id="test-project",
            organization_id="test-org",
            workflow_run_id="test-run",
            stages=["export"],
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
                    "content": "# generated client",
                    "language": "python",
                    "file_type": "sdk",
                }
            ],
            test_suite=[],
            test_run_summary={"total": 0, "passed": 0, "failed": 0, "skipped": 0},
            errors=[],
            total_tokens_used=0,
            status="running",
            progress_percent=0,
            current_node="",
        )

    @pytest.mark.asyncio
    async def test_github_export_skips_when_not_configured(self, mock_state):
        """GitHub export is skipped when GitHub App is not configured."""
        with patch("app.workflows.agents.export_agent.get_settings") as mock_settings:
            mock_settings.return_value.github_app_id = None
            agent = ExportAgent()
            result = await agent._package_github(
                project_id="test-project",
                export_types=["github"],
                generated_files=mock_state["generated_files"],
            )
            assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_github_export_creates_repo(self, mock_state):
        """GitHub export creates a repository and pushes files."""
        with patch("app.workflows.agents.export_agent.get_settings") as mock_settings, \
             patch("app.workflows.agents.export_agent.GitHubAppClient") as MockClient, \
             patch("app.workflows.agents.export_agent.storage_service") as mock_storage:

            mock_settings.return_value.github_app_id = "12345"
            mock_settings.return_value.github_app_private_key_path = None
            mock_settings.return_value.github_app_client_id = None
            mock_settings.return_value.github_oauth_redirect_uri = None

            gh_client = MagicMock()
            gh_client.create_repository = AsyncMock(
                return_value={"full_name": "test-org/test-repo"}
            )
            gh_client.push_files_via_git_data_api = AsyncMock(return_value="abc123")
            gh_client.get_installation_token = AsyncMock(return_value="token")
            MockClient.return_value = gh_client

            mock_storage.upload = AsyncMock()

            agent = ExportAgent()
            result = await agent._package_github(
                project_id="test-project",
                export_types=["github"],
                generated_files=mock_state["generated_files"],
                github_repo_name="test-repo",
            )
            assert result["type"] == "github"
            assert result["status"] == "completed"
            assert "repo_url" in result
