"""Tests for GitHub service client configuration and vendor URL wiring."""

from __future__ import annotations

from typing import Any
import pytest
import httpx

from app.core.config import Settings
from app.services.github_service import (
    GITHUB_API_BASE,
    GITHUB_OAUTH_AUTHORIZE_URL,
    GITHUB_OAUTH_TOKEN_URL,
    GitHubAppClient,
    GitHubOAuthClient,
)
from tests.fakes import FakeVaultClient


def test_github_clients_default_urls():
    """Verify default URLs when settings use standard GitHub endpoints."""
    settings = Settings(
        app_env="development",
        jwt_private_key_path="backend/tests/fixtures/jwt_private.pem",
        jwt_public_key_path="backend/tests/fixtures/jwt_public.pem",
        github_app_id="app-123",
        github_app_client_id="client-xyz",
    )

    app_client = GitHubAppClient(settings)
    assert app_client.api_base_url == GITHUB_API_BASE

    oauth_client = GitHubOAuthClient(settings)
    assert oauth_client.api_base_url == GITHUB_API_BASE
    assert oauth_client.authorize_url == GITHUB_OAUTH_AUTHORIZE_URL
    assert oauth_client.token_url == GITHUB_OAUTH_TOKEN_URL


def test_github_clients_custom_urls():
    """Verify custom URLs from Settings override default endpoints (e.g. GitHub Enterprise)."""
    settings = Settings(
        app_env="development",
        jwt_private_key_path="backend/tests/fixtures/jwt_private.pem",
        jwt_public_key_path="backend/tests/fixtures/jwt_public.pem",
        github_app_id="app-123",
        github_app_client_id="client-xyz",
        github_api_base_url="https://ghe.mycorp.internal/api/v3",
        github_oauth_authorize_url="https://ghe.mycorp.internal/login/oauth/authorize",
        github_oauth_token_url="https://ghe.mycorp.internal/login/oauth/access_token",
    )

    app_client = GitHubAppClient(settings)
    assert app_client.api_base_url == "https://ghe.mycorp.internal/api/v3"

    oauth_client = GitHubOAuthClient(settings)
    assert oauth_client.api_base_url == "https://ghe.mycorp.internal/api/v3"
    assert oauth_client.authorize_url == "https://ghe.mycorp.internal/login/oauth/authorize"
    assert oauth_client.token_url == "https://ghe.mycorp.internal/login/oauth/access_token"

    auth_url = oauth_client.get_authorization_url(state="test_state")
    assert auth_url.startswith("https://ghe.mycorp.internal/login/oauth/authorize?")
    assert "state=test_state" in auth_url
    assert "client_id=client-xyz" in auth_url


@pytest.mark.asyncio
async def test_github_oauth_client_requests_use_configured_urls(monkeypatch):
    """Verify exchange_code, get_user_info, and get_user_emails use configured URLs."""
    settings = Settings(
        app_env="development",
        jwt_private_key_path="backend/tests/fixtures/jwt_private.pem",
        jwt_public_key_path="backend/tests/fixtures/jwt_public.pem",
        github_app_client_id="client-xyz",
        github_app_client_secret_vault_path="secret/github/client_secret",
        github_oauth_redirect_uri="https://apiweaver.internal/callback",
        github_api_base_url="https://ghe.mycorp.internal/api/v3",
        github_oauth_token_url="https://ghe.mycorp.internal/login/oauth/access_token",
    )

    oauth_client = GitHubOAuthClient(settings)
    fake_vault = FakeVaultClient()
    await fake_vault.write_secret("secret/github/client_secret", {"client_secret": "sec-test"})
    oauth_client.vault_client = fake_vault

    captured_requests = []

    class _CaptureTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured_requests.append({
                "method": request.method,
                "url": str(request.url),
            })
            if "access_token" in str(request.url):
                return httpx.Response(200, json={"access_token": "gho_test_token"})
            elif str(request.url).endswith("/user"):
                return httpx.Response(200, json={"id": 1, "login": "gheuser"})
            elif str(request.url).endswith("/user/emails"):
                return httpx.Response(200, json=[{"email": "gheuser@mycorp.com", "primary": True}])
            return httpx.Response(404)

    original_client = httpx.AsyncClient

    def _mock_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = _CaptureTransport()
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _mock_async_client)

    token_data = await oauth_client.exchange_code("code_123")
    assert token_data["access_token"] == "gho_test_token"

    user_info = await oauth_client.get_user_info("gho_test_token")
    assert user_info["login"] == "gheuser"

    emails = await oauth_client.get_user_emails("gho_test_token")
    assert emails[0]["email"] == "gheuser@mycorp.com"

    urls = [r["url"] for r in captured_requests]
    assert urls[0] == "https://ghe.mycorp.internal/login/oauth/access_token"
    assert urls[1] == "https://ghe.mycorp.internal/api/v3/user"
    assert urls[2] == "https://ghe.mycorp.internal/api/v3/user/emails"
