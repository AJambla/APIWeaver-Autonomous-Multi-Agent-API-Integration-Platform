"""Tests for GitHub service client configuration and vendor URL wiring."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

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
    """Verify exchange_code, and get_user_info use configured URLs."""
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


    urls = [r["url"] for r in captured_requests]
    assert urls[0] == "https://ghe.mycorp.internal/login/oauth/access_token"
    assert urls[1] == "https://ghe.mycorp.internal/api/v3/user"


class _FakeGitHub(httpx.AsyncBaseTransport):
    """Just enough of the Git Data API to tell empty, missing-branch and normal repos apart."""

    def __init__(self, *, empty: bool, branches: dict[str, str] | None = None) -> None:
        self.empty = empty
        self.branches = dict(branches or {})
        self.commits: dict[str, dict[str, Any]] = {sha: {"tree": f"tree-{sha}"} for sha in self.branches.values()}
        self.calls: list[tuple[str, str, Any]] = []
        self._n = 0

    def _sha(self, kind: str) -> str:
        self._n += 1
        return f"{kind}{self._n}"

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        import json as _json

        path = request.url.path.removeprefix("/repos/acme/sdk")
        body = _json.loads(request.content) if request.content else None
        self.calls.append((request.method, path, body))
        if request.method == "GET" and path.startswith("/git/refs/heads/"):
            if self.empty:
                return httpx.Response(409, json={"message": "Git Repository is empty."})
            sha = self.branches.get(path.removeprefix("/git/refs/heads/"))
            return httpx.Response(200, json={"object": {"sha": sha}}) if sha else httpx.Response(404)
        if request.method == "GET" and path == "":
            return httpx.Response(200, json={"default_branch": "main"})
        if request.method == "PUT" and path == "/contents/README.md":
            sha = self._sha("init")
            self.empty = False
            self.branches[body["branch"]] = sha
            self.commits[sha] = {"tree": f"tree-{sha}"}
            return httpx.Response(201, json={"commit": {"sha": sha}})
        if request.method == "GET" and path.startswith("/git/commits/"):
            commit = self.commits.get(path.removeprefix("/git/commits/"))
            return httpx.Response(200, json={"tree": {"sha": commit["tree"]}}) if commit else httpx.Response(404)
        if request.method == "POST" and path == "/git/blobs":
            if self.empty:
                return httpx.Response(409, json={"message": "Git Repository is empty."})
            return httpx.Response(201, json={"sha": self._sha("blob")})
        if request.method == "POST" and path == "/git/trees":
            return httpx.Response(201, json={"sha": self._sha("tree")})
        if request.method == "POST" and path == "/git/commits":
            sha = self._sha("commit")
            self.commits[sha] = {"tree": body["tree"], "parents": body["parents"]}
            return httpx.Response(201, json={"sha": sha})
        if request.method == "POST" and path == "/git/refs":
            self.branches[body["ref"].removeprefix("refs/heads/")] = body["sha"]
            return httpx.Response(201, json={})
        if request.method == "PATCH" and path.startswith("/git/refs/heads/"):
            branch = path.removeprefix("/git/refs/heads/")
            if branch not in self.branches or body.get("force"):
                return httpx.Response(422)
            self.branches[branch] = body["sha"]
            return httpx.Response(200, json={})
        return httpx.Response(404)


def _client_with(monkeypatch, fake: _FakeGitHub) -> GitHubAppClient:
    original = httpx.AsyncClient

    def _patched(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = fake
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _patched)
    return GitHubAppClient(
        Settings(
            app_env="development",
            jwt_private_key_path="backend/tests/fixtures/jwt_private.pem",
            jwt_public_key_path="backend/tests/fixtures/jwt_public.pem",
        )
    )


FILES = [{"path": "client.py", "content": "x = 1\n"}]


@pytest.mark.asyncio
async def test_push_into_an_empty_repository_initializes_it_first(monkeypatch):
    fake = _FakeGitHub(empty=True)
    client = _client_with(monkeypatch, fake)

    commit = await client.push_files_via_git_data_api("tok", "acme/sdk", FILES, "SDK", "main")

    assert fake.branches["main"] == commit
    assert fake.commits[commit]["parents"] == ["init1"]


@pytest.mark.asyncio
async def test_push_to_a_new_branch_creates_it_from_the_default_branch(monkeypatch):
    fake = _FakeGitHub(empty=False, branches={"main": "base"})
    client = _client_with(monkeypatch, fake)

    commit = await client.push_files_via_git_data_api("tok", "acme/sdk", FILES, "SDK", "sdk-v1")

    assert fake.branches == {"main": "base", "sdk-v1": commit}
    assert fake.commits[commit]["parents"] == ["base"]


@pytest.mark.asyncio
async def test_push_to_an_existing_branch_fast_forwards_without_force(monkeypatch):
    fake = _FakeGitHub(empty=False, branches={"main": "base"})
    client = _client_with(monkeypatch, fake)

    commit = await client.push_files_via_git_data_api("tok", "acme/sdk", FILES, "SDK", "main")

    assert fake.branches["main"] == commit
    patches = [body for method, path, body in fake.calls if method == "PATCH"]
    assert patches == [{"sha": commit, "force": False}]


def test_authorization_url_is_properly_encoded():
    settings = Settings(
        app_env="development",
        jwt_private_key_path="backend/tests/fixtures/jwt_private.pem",
        jwt_public_key_path="backend/tests/fixtures/jwt_public.pem",
        github_app_client_id="client-xyz",
        github_oauth_redirect_uri="https://app.example/cb?next=/a&b=1",
    )
    url = GitHubOAuthClient(settings).get_authorization_url(state="s t")
    assert "redirect_uri=https%3A%2F%2Fapp.example%2Fcb%3Fnext%3D%2Fa%26b%3D1" in url
    assert "scope=repo+read%3Auser+read%3Aorg" in url
    assert "state=s+t" in url
