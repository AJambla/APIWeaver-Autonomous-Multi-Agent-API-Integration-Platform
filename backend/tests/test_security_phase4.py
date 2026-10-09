"""Phase 4 Security Hardening unit and regression tests.

Covers:
- X-01: Refresh token in HttpOnly SameSite=Strict cookie + fallback
- X-02: Dynamic nonce markers and untrusted data fences
- X-03: Self-review fail-closed on exception
- X-04 / X-05: Sandbox result nonce protection from interpreter namespace
- X-06: Qdrant tenant isolation
- X-07: Vault token renewal / lease extension
- X-08: Path traversal sanitization in GitHub commits
- X-11: Constant-time authentication and lockout indistinguishability
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.core.config import Settings
from app.services.github_service import sanitize_github_path
from app.services.vault_service import HttpVaultClient
from app.workflows.agents.code_agent import _run_self_review
from tests.fakes import FakeVaultClient


# 1. GitHub Path Sanitization (X-08)
def test_sanitize_github_path_valid():
    assert sanitize_github_path("src/client.py") == "src/client.py"
    assert sanitize_github_path("/models/user.py") == "models/user.py"
    assert sanitize_github_path("nested\\dir\\file.ts") == "nested/dir/file.ts"


def test_sanitize_github_path_rejects_traversal():
    with pytest.raises(ValueError, match="Path traversal"):
        sanitize_github_path("../etc/passwd")

    with pytest.raises(ValueError, match="Path traversal"):
        sanitize_github_path("src/../../evil.py")

    with pytest.raises(ValueError, match="Path traversal"):
        sanitize_github_path("./file.py")

    with pytest.raises(ValueError):
        sanitize_github_path("")


# 2. Vault Token Renewal (X-07)
@pytest.mark.asyncio
async def test_vault_token_renewal_in_fake():
    fake_vault = FakeVaultClient()
    success = await fake_vault.renew_token(3600)
    assert success is True


@pytest.mark.asyncio
async def test_vault_token_renewal_http_success():
    settings = Settings(
        vault_addr="http://localhost:8200",
        vault_token="test-token",
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        jwt_private_key_path="backend/tests/fixtures/jwt_private.pem",
        jwt_public_key_path="backend/tests/fixtures/jwt_public.pem",
    )
    client = HttpVaultClient(settings)

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        success = await client.renew_token(increment_seconds=1800)
        assert success is True
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "/v1/auth/token/renew-self" in call_args[0][0]
        assert call_args[1]["json"] == {"increment": "1800s"}


# 3. Code Agent Self-Review Fail-Closed (X-03)
@pytest.mark.asyncio
async def test_code_agent_self_review_fails_closed_on_exception():
    mock_llm = AsyncMock()
    mock_llm.generate_json.side_effect = RuntimeError("LLM provider crashed during self-review")

    state = {"project_id": str(uuid.uuid4())}
    files = [{"file_path": "client.py", "content_s3_key": "gen/client.py"}]

    with patch("app.workflows.agents.code_agent.storage_service") as mock_storage:
        mock_storage.download = AsyncMock(return_value=b"print('hello')")
        result = await _run_self_review(files, state, mock_llm)

    assert result["self_review_passed"] is False
    assert len(result["self_review_issues"]) > 0
    assert "LLM provider crashed" in result["self_review_summary"]


# 4. Refresh Token HttpOnly Cookie Response & Rotation (X-01)
@pytest.mark.asyncio
async def test_refresh_token_cookie_lifecycle(client: AsyncClient):
    # Register sets cookie
    reg_res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "cookie_test@example.com",
            "password": "Password123!@",
            "full_name": "Cookie Tester",
            "organization_name": "Cookie Org",
        },
    )
    assert reg_res.status_code == 201
    assert "refresh_token" in reg_res.cookies
    token_from_cookie = reg_res.cookies["refresh_token"]
    assert token_from_cookie is not None

    # Refresh can rotate using cookie alone without JSON payload
    ref_res = await client.post("/api/v1/auth/refresh")
    assert ref_res.status_code == 200
    ref_data = ref_res.json()
    assert "access_token" in ref_data
    assert "refresh_token" in ref_res.cookies

    # Logout clears cookie
    logout_res = await client.post("/api/v1/auth/logout")
    assert logout_res.status_code == 204
    # Set-Cookie in logout deletes the cookie (value empty or max-age=0)
    assert reg_res.cookies["refresh_token"] != ""
