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
    async def test_github_export_creates_repo(
        self, session_factory, db, fake_vault, mock_state
    ):
        """GitHub export resolves the owner's GitHub connection + installation and pushes files."""
        from app.models.github import GitHubConnection
        from tests.conftest import (
            add_project_member,
            make_org,
            make_project,
            make_user,
        )

        user = await make_user(db, email="github-exporter@example.com")
        org = await make_org(db, name="GitHub Export Org")
        project = await make_project(db, org=org)
        await add_project_member(db, project=project, user=user)
        db.add(
            GitHubConnection(
                user_id=user.id,
                github_user_id="98765",
                github_username="github-exporter",
                access_token_vault_path=f"github/connections/{user.id}",
            )
        )
        await db.commit()

        await fake_vault.write_secret(
            f"github/connections/{user.id}", {"access_token": "gho_test_token"}
        )

        generated_files = [
            {
                "file_path": "client.py",
                "content_s3_key": f"generated/{project.id}/client.py",
                "language": "python",
                "file_type": "sdk",
            }
        ]

        with patch("app.workflows.agents.export_agent.get_settings") as mock_settings, \
             patch("app.workflows.agents.export_agent.GitHubAppClient") as MockClient, \
             patch("app.workflows.agents.export_agent.create_vault_client", return_value=fake_vault), \
             patch("app.workflows.agents.export_agent.storage_service") as mock_storage:

            mock_settings.return_value.github_app_id = "12345"
            mock_settings.return_value.github_app_private_key_path = None
            mock_settings.return_value.github_app_client_id = None
            mock_settings.return_value.github_oauth_redirect_uri = None

            gh_client = MagicMock()
            gh_client.get_user_installations = AsyncMock(
                return_value=[{"id": 42, "account": {"login": "github-exporter"}}]
            )
            gh_client.get_installation_token = AsyncMock(return_value="installation-token")
            gh_client.create_repository = AsyncMock(
                return_value={"full_name": "test-org/test-repo"}
            )
            gh_client.push_files_via_git_data_api = AsyncMock(return_value="abc123")
            MockClient.return_value = gh_client

            mock_storage.upload = AsyncMock()
            mock_storage.download = AsyncMock(return_value=b"# generated client")

            agent = ExportAgent(session_factory=session_factory)
            result = await agent._package_github(
                project_id=str(project.id),
                export_types=["github"],
                generated_files=generated_files,
                github_repo_name="test-repo",
            )

            assert result["type"] == "github"
            assert result["status"] == "completed"
            assert result["repo_url"] == "https://github.com/test-org/test-repo"

            gh_client.get_user_installations.assert_awaited_once_with("gho_test_token")
            gh_client.get_installation_token.assert_awaited_once_with(42)
            mock_storage.download.assert_awaited_once_with(
                f"generated/{project.id}/client.py"
            )

            push_kwargs = gh_client.push_files_via_git_data_api.await_args.kwargs
            pushed = {f["path"]: f["content"] for f in push_kwargs["files"]}
            assert pushed["client.py"] == "# generated client"
            assert "README.md" in pushed
            assert result["metadata"]["files_pushed"] == 2
            mock_storage.upload.assert_awaited_once()
