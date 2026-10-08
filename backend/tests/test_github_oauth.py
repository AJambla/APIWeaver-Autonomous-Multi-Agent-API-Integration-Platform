"""Tests for GitHub OAuth flow."""

from __future__ import annotations

import uuid

import pytest

from app.api.v1.github import create_github_app_client, create_github_oauth_client
from app.models.github import GitHubConnection


class _StubOAuth:
    def get_authorization_url(self, state: str, scopes: list[str] | None = None) -> str:
        return f"https://github.com/login/oauth/authorize?state={state}"


class TestGitHubOAuth:
    """Tests for GitHub OAuth endpoints."""

    @pytest.mark.asyncio
    async def test_connect_creates_oauth_state(self, client, auth_headers, app):
        """POST /github/connect creates an OAuth state token."""
        app.dependency_overrides[create_github_oauth_client] = lambda: _StubOAuth()

        response = await client.post(
            "/api/v1/github/connect",
            headers=auth_headers,
        )
        assert response.status_code in (200, 302)
        assert "auth_url" in response.json()
        assert "state" in response.json()

    @pytest.mark.asyncio
    async def test_connect_requires_auth(self, client):
        """GitHub connect requires authentication."""
        response = await client.post("/api/v1/github/connect")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_status_returns_connection_info(self, client, auth_headers, session_factory):
        """GET /github/status returns connection state."""
        me = await client.get("/api/v1/auth/me", headers=auth_headers)
        user_id = uuid.UUID(me.json()["user"]["id"])

        async with session_factory() as session:
            conn = GitHubConnection(
                user_id=user_id,
                github_user_id="12345",
                github_username="testuser",
            )
            session.add(conn)
            await session.commit()

        response = await client.get("/api/v1/github/status", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["connected"] is True
        assert data["github_username"] == "testuser"
        assert data["installations"] == []

    @pytest.mark.asyncio
    async def test_status_returns_installations_from_github_app(
        self, client, auth_headers, session_factory, fake_vault, app
    ):
        """GET /github/status retrieves accessible GitHub App installations."""
        me = await client.get("/api/v1/auth/me", headers=auth_headers)
        user_id = uuid.UUID(me.json()["user"]["id"])

        access_path = f"secret/github/connections/{user_id}/access"
        await fake_vault.write_secret(access_path, {"token": "ghu_token_123"})

        async with session_factory() as session:
            conn = GitHubConnection(
                user_id=user_id,
                github_user_id="12345",
                github_username="testuser",
                access_token_vault_path=access_path,
            )
            session.add(conn)
            await session.commit()

        class _StubAppClient:
            async def get_user_installations(self, token: str):
                assert token == "ghu_token_123"
                return [
                    {"id": 999, "account": {"login": "my-org", "type": "Organization"}},
                    {"id": 1000, "account": {"login": "testuser", "type": "User"}},
                ]

        app.dependency_overrides[create_github_app_client] = lambda: _StubAppClient()

        response = await client.get("/api/v1/github/status", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["connected"] is True
        assert len(data["installations"]) == 2
        assert data["installations"][0] == {"id": 999, "account": "my-org", "account_type": "Organization"}
        assert data["installations"][1] == {"id": 1000, "account": "testuser", "account_type": "User"}

    @pytest.mark.asyncio
    async def test_disconnect_revokes_connection(
        self, client, auth_headers, session_factory, fake_vault
    ):
        """DELETE /github/disconnect revokes an active connection and deletes tokens from Vault."""
        me = await client.get("/api/v1/auth/me", headers=auth_headers)
        user_id = uuid.UUID(me.json()["user"]["id"])

        access_path = f"secret/github/connections/{user_id}/access"
        refresh_path = f"secret/github/connections/{user_id}/refresh"
        await fake_vault.write_secret(access_path, {"token": "ghp_access_token"})
        await fake_vault.write_secret(refresh_path, {"token": "ghr_refresh_token"})

        async with session_factory() as session:
            conn = GitHubConnection(
                user_id=user_id,
                github_user_id="12345",
                github_username="testuser",
                access_token_vault_path=access_path,
                refresh_token_vault_path=refresh_path,
            )
            session.add(conn)
            await session.commit()

        response = await client.delete(
            "/api/v1/github/disconnect",
            headers=auth_headers,
        )
        assert response.status_code == 204

        status_res = await client.get("/api/v1/github/status", headers=auth_headers)
        assert status_res.status_code == 200
        assert status_res.json()["connected"] is False

        # Verify secrets are deleted from Vault
        assert await fake_vault.read_secret(access_path) is None
        assert await fake_vault.read_secret(refresh_path) is None

    @pytest.mark.asyncio
    async def test_repos_requires_connection(self, client, auth_headers):
        """GET /github/repos requires an active GitHub connection."""
        response = await client.get("/api/v1/github/repos", headers=auth_headers)
        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_repos_returns_repositories_from_github(
        self, client, auth_headers, session_factory, fake_vault, app
    ):
        """GET /github/repos returns user repositories using Vault token."""
        me = await client.get("/api/v1/auth/me", headers=auth_headers)
        user_id = uuid.UUID(me.json()["user"]["id"])

        access_path = f"secret/github/connections/{user_id}/access"
        await fake_vault.write_secret(access_path, {"token": "ghu_repo_token"})

        async with session_factory() as session:
            conn = GitHubConnection(
                user_id=user_id,
                github_user_id="12345",
                github_username="testuser",
                access_token_vault_path=access_path,
            )
            session.add(conn)
            await session.commit()

        class _StubAppClient:
            async def get_user_repositories(self, token: str):
                assert token == "ghu_repo_token"
                return [
                    {
                        "id": 101,
                        "name": "api-weaver",
                        "full_name": "testuser/api-weaver",
                        "private": True,
                        "owner": {"login": "testuser"},
                        "default_branch": "main",
                    },
                    {
                        "id": 102,
                        "name": "docs-site",
                        "full_name": "my-org/docs-site",
                        "private": False,
                        "owner": {"login": "my-org"},
                        "default_branch": "master",
                    },
                ]

        app.dependency_overrides[create_github_app_client] = lambda: _StubAppClient()

        response = await client.get("/api/v1/github/repos", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["repos"]) == 2
        assert data["repos"][0]["name"] == "api-weaver"
        assert data["repos"][0]["private"] is True
        assert data["repos"][1]["full_name"] == "my-org/docs-site"
        assert data["repos"][1]["default_branch"] == "master"
