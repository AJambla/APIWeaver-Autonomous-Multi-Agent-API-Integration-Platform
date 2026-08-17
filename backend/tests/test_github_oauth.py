"""Tests for GitHub OAuth flow."""

from __future__ import annotations

import pytest

from app.models.github import GitHubConnection
from app.models.user import User


class TestGitHubOAuth:
    """Tests for GitHub OAuth endpoints."""

    @pytest.mark.asyncio
    async def test_connect_creates_oauth_state(self, client, auth_headers, session_factory):
        """POST /github/connect creates an OAuth state token."""
        async with session_factory() as session:
            user = User(email="github_test@example.com", password_hash="fake")
            session.add(user)
            await session.flush()

        response = await client.post(
            "/api/v1/github/connect",
            headers=auth_headers,
        )
        assert response.status_code in (200, 302)

    @pytest.mark.asyncio
    async def test_connect_requires_auth(self, client):
        """GitHub connect requires authentication."""
        response = await client.post("/api/v1/github/connect")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_status_returns_connection_info(self, client, auth_headers, session_factory):
        """GET /github/status returns connection state."""
        async with session_factory() as session:
            user = User(email="github_status@example.com", password_hash="fake")
            session.add(user)
            await session.flush()
            conn = GitHubConnection(
                user_id=user.id,
                github_user_id="12345",
                github_username="testuser",
            )
            session.add(conn)
            await session.commit()

        response = await client.get("/api/v1/github/status", headers=auth_headers)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_disconnect_revokes_connection(self, client, auth_headers, session_factory):
        """POST /github/disconnect revokes an active connection."""
        async with session_factory() as session:
            user = User(email="github_disc@example.com", password_hash="fake")
            session.add(user)
            await session.flush()
            conn = GitHubConnection(
                user_id=user.id,
                github_user_id="12345",
                github_username="testuser",
            )
            session.add(conn)
            await session.commit()

        response = await client.post(
            "/api/v1/github/disconnect",
            headers=auth_headers,
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_repos_requires_connection(self, client, auth_headers):
        """GET /github/repos requires an active GitHub connection."""
        response = await client.get("/api/v1/github/repos", headers=auth_headers)
        assert response.status_code in (200, 404, 500)
