"""Tests for security hardening and multi-tenancy protections."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services.ingestion_service import sanitize_filename
from app.services.storage_service import validate_storage_key
from app.services.vault_service import validate_vault_path
from tests.fakes import FakeVaultClient, InMemoryObjectStorage


def _make_settings(base: Settings, **kwargs) -> Settings:
    values = {
        "database_url": "sqlite+aiosqlite:///:memory:",
        "redis_url": base.redis_url,
        "jwt_private_key_path": base.jwt_private_key_path,
        "jwt_public_key_path": base.jwt_public_key_path,
    }
    values.update(kwargs)
    return Settings(**values)


class TestSandboxIsolationSecurity:
    """Ensure sandbox executor isolates untrusted code and refuses in-process execution in production/staging."""

    def test_staging_refuses_mock_sandbox(self, test_settings: Settings) -> None:
        with pytest.raises(ValidationError, match="SANDBOX_BACKEND=mock"):
            _make_settings(test_settings, app_env="staging", sandbox_backend="mock")

    def test_production_refuses_mock_sandbox(self, test_settings: Settings) -> None:
        with pytest.raises(ValidationError, match="SANDBOX_BACKEND=mock"):
            _make_settings(test_settings, app_env="production", sandbox_backend="mock")

    def test_storage_key_rejects_traversal(self) -> None:
        with pytest.raises(ValueError, match="Invalid or unsafe storage key"):
            validate_storage_key("../secret.txt")

        with pytest.raises(ValueError, match="Invalid or unsafe storage key"):
            validate_storage_key("projects/123/../../etc/passwd")

        with pytest.raises(ValueError, match="Invalid or unsafe storage key"):
            validate_storage_key(r"projects\123\..\traversal")

        with pytest.raises(ValueError, match="Invalid or unsafe storage key"):
            validate_storage_key("")

    @pytest.mark.asyncio
    async def test_in_memory_storage_rejects_traversal(self) -> None:
        storage = InMemoryObjectStorage()
        with pytest.raises(ValueError, match="Invalid or unsafe storage key"):
            await storage.put(key="../evil", content=b"evil")

        with pytest.raises(ValueError, match="Invalid or unsafe storage key"):
            await storage.get(key="../evil")

        with pytest.raises(ValueError, match="Invalid or unsafe storage key"):
            await storage.delete(key="../evil")


class TestVaultPathValidation:
    """Ensure Vault operations reject path traversal."""

    def test_vault_path_rejects_traversal(self) -> None:
        with pytest.raises(ValueError, match="Path traversal or empty path not permitted"):
            validate_vault_path("../evil/path")

        with pytest.raises(ValueError, match="Path traversal or empty path not permitted"):
            validate_vault_path("secret/orgs/../../other_org")

        with pytest.raises(ValueError, match="Path traversal or empty path not permitted"):
            validate_vault_path("")

    @pytest.mark.asyncio
    async def test_fake_vault_rejects_traversal(self) -> None:
        vault = FakeVaultClient()
        with pytest.raises(ValueError, match="Path traversal or empty path not permitted"):
            await vault.write_secret("../forbidden", {"token": "123"})

        with pytest.raises(ValueError, match="Path traversal or empty path not permitted"):
            await vault.read_secret("../forbidden")

        with pytest.raises(ValueError, match="Path traversal or empty path not permitted"):
            await vault.delete_secret("../forbidden")


class TestFilenameSanitization:
    """Ensure document upload filenames are sanitized defensively."""

    def test_sanitize_filename_removes_traversal(self) -> None:
        assert sanitize_filename("../../etc/passwd") == "passwd"
        assert sanitize_filename("..\\..\\windows\\system32\\cmd.exe") == "cmd.exe"
        assert sanitize_filename("..") == "document"
        assert sanitize_filename(".") == "document"
        assert sanitize_filename("") == "document"

    def test_sanitize_filename_removes_control_characters(self) -> None:
        assert sanitize_filename("spec\x00file\x1f.json") == "specfile.json"

    def test_sanitize_filename_bounds_length(self) -> None:
        long_name = "a" * 300 + ".json"
        sanitized = sanitize_filename(long_name)
        assert len(sanitized) <= 255


class TestSecurityResponseHeaders:
    """Ensure HTTP security response headers are enforced."""

    @pytest.mark.asyncio
    async def test_health_endpoint_carries_security_headers(self, client) -> None:
        response = await client.get("/healthz")
        assert response.status_code == 200
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert response.headers.get("X-XSS-Protection") == "1; mode=block"
        assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert "camera=()" in response.headers.get("Permissions-Policy", "")


class TestStartupEnvironmentValidation:
    """Ensure startup preflight checks fail-loud on misconfigured or missing environment dependencies."""

    def test_validate_startup_environment_passes_on_valid_dev(self, test_settings: Settings) -> None:
        from app.core.config import validate_startup_environment

        validate_startup_environment(test_settings)

    def test_validate_startup_environment_requires_database_url(self, test_settings: Settings) -> None:
        from app.core.config import validate_startup_environment

        settings = test_settings.model_copy(update={"database_url": "   "})
        with pytest.raises(ValueError, match="DATABASE_URL must be set and non-empty"):
            validate_startup_environment(settings)

    def test_validate_startup_environment_requires_redis_url(self, test_settings: Settings) -> None:
        from app.core.config import validate_startup_environment

        settings = test_settings.model_copy(update={"redis_url": ""})
        with pytest.raises(ValueError, match="REDIS_URL must be set and non-empty"):
            validate_startup_environment(settings)

    def test_validate_startup_environment_fails_missing_jwt_keys(
        self, test_settings: Settings, tmp_path: Path
    ) -> None:
        from app.core.config import validate_startup_environment

        settings = test_settings.model_copy(
            update={"jwt_private_key_path": tmp_path / "nonexistent.pem"}
        )
        with pytest.raises(FileNotFoundError, match="JWT private key not found"):
            validate_startup_environment(settings)

    def test_validate_startup_environment_requires_llm_key_in_production(
        self, test_settings: Settings
    ) -> None:
        from app.core.config import validate_startup_environment

        prod_no_llm = test_settings.model_copy(
            update={
                "app_env": "production",
                "openai_api_key": "",
                "anthropic_api_key": "",
            }
        )
        with pytest.raises(
            ValueError,
            match="Production mode strictly requires at least one configured LLM provider key",
        ):
            validate_startup_environment(prod_no_llm)

    def test_validate_startup_environment_accepts_production_with_openai_key(
        self, test_settings: Settings
    ) -> None:
        from app.core.config import validate_startup_environment

        prod = test_settings.model_copy(
            update={
                **SAFE_PRODUCTION,
                "openai_api_key": "sk-proj-test12345",
            }
        )
        validate_startup_environment(prod)

    def test_validate_startup_environment_accepts_production_with_anthropic_key(
        self, test_settings: Settings
    ) -> None:
        from app.core.config import validate_startup_environment

        prod = test_settings.model_copy(
            update={
                **SAFE_PRODUCTION,
                "anthropic_api_key": "sk-ant-test12345",
            }
        )
        validate_startup_environment(prod)




SAFE_PRODUCTION = {
    "app_env": "production",
    "cors_allowed_origins": "https://app.apiweaver.example",
    "vault_addr": "https://vault.internal:8200",
    "vault_token": "hvs.CAESIJ-not-a-dev-token",
    "metrics_token": "m" * 32,
    "aws_access_key_id": None,
}


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"cors_allowed_origins": "*"}, "contains '*'"),
        ({"cors_allowed_origins": "http://app.example"}, "is not https"),
        ({"metrics_token": "prod_scrape_token_local_test"}, "METRICS_TOKEN"),
        ({"vault_token": "root"}, "VAULT_TOKEN"),
        ({"vault_token": None}, "VAULT_TOKEN"),
        ({"vault_addr": "http://vault:8200"}, "VAULT_ADDR"),
        ({"aws_access_key_id": "minioadmin"}, "MinIO default"),
    ],
)
def test_production_refuses_development_defaults(test_settings: Settings, override, fragment) -> None:
    from app.core.config import validate_startup_environment

    settings = test_settings.model_copy(
        update={**SAFE_PRODUCTION, "openai_api_key": "sk-x", **override}
    )
    with pytest.raises(ValueError, match="unsafe configuration") as raised:
        validate_startup_environment(settings)
    assert fragment in str(raised.value)


def test_a_blank_metrics_token_counts_as_unset(test_settings: Settings) -> None:
    """An empty token mounted /metrics behind compare_digest("", "")."""
    settings = Settings(**{**test_settings.model_dump(), "metrics_token": "  "})
    assert settings.metrics_token is None


async def test_password_hashing_does_not_block_the_event_loop() -> None:
    """Argon2 takes ~200 ms; run inline it froze every other request on the worker.

    Measured as the longest gap between ticks of a concurrent task, against the duration
    of one synchronous hash on this machine: blocking would make the gap at least that
    long. (Counting ticks was flaky on Windows, where sleep(0.005) lasts ~15.6 ms.)
    """
    import asyncio
    import time

    from app.core.security import hash_password, hash_password_async, verify_password_async

    started = time.perf_counter()
    hash_password("calibration password")
    one_hash = time.perf_counter() - started

    gaps: list[float] = []
    stop = False

    async def ticker() -> None:
        last = time.perf_counter()
        while not stop:
            await asyncio.sleep(0)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    task = asyncio.create_task(ticker())
    hashed = await hash_password_async("correct horse battery")
    assert await verify_password_async("correct horse battery", hashed)
    stop = True
    await task

    assert max(gaps) < one_hash / 2, (max(gaps), one_hash)


def test_log_redaction_removes_every_character_of_a_real_api_key() -> None:
    """Keys are token_urlsafe output; '-' and '_' used to end the redaction early."""
    from app.api.v1.api_keys import _generate_key
    from app.core.logging import REDACTED, _redact_value

    for _ in range(500):
        key, _hash = _generate_key()
        redacted = _redact_value(f"rejected key={key} for org")
        assert redacted == f"rejected key={REDACTED} for org", redacted


async def test_an_unreachable_denylist_fails_closed_with_503(
    client, fake_redis, monkeypatch
) -> None:
    """If revocation cannot be checked the token is refused, as a 503 rather than a 500."""
    from redis.exceptions import TimeoutError as RedisTimeoutError

    from tests.test_documents import _project_headers

    _, headers = await _project_headers(client)

    async def unreachable(*_args, **_kwargs):
        raise RedisTimeoutError("Timeout reading from socket")

    monkeypatch.setattr(fake_redis, "exists", unreachable)
    res = await client.get("/api/v1/projects", headers=headers)

    assert res.status_code == 503, res.text
    assert "Timeout reading" not in res.text


def test_token_counts_are_logged_but_credentials_are_not() -> None:
    from app.core.logging import REDACTED, _redact_value

    event = {
        "tokens_used": 1200,
        "total_tokens": 3400,
        "speed_tokens_per_second": 950.5,
        "tokens_before": 10,
        "access_token": "eyJabc",
        "refresh_tokens": ["r1"],
        "token": "t",
        "api_token": "x",
    }
    redacted = _redact_value(event)
    assert redacted["tokens_used"] == 1200
    assert redacted["total_tokens"] == 3400
    assert redacted["speed_tokens_per_second"] == 950.5
    assert redacted["tokens_before"] == 10
    for secret_key in ("access_token", "refresh_tokens", "token", "api_token"):
        assert redacted[secret_key] == REDACTED, secret_key


def test_llm_probe_reports_a_category_not_the_raw_provider_error() -> None:
    import httpx

    from app.api.v1.health import describe_provider_error

    request = httpx.Request("POST", "https://llm.example/v1/chat?key=sk-secret-in-url")
    rejected = httpx.HTTPStatusError(
        "401 Unauthorized: {'error': 'bad key sk-secret-in-body'}",
        request=request,
        response=httpx.Response(401, request=request),
    )
    message = describe_provider_error(rejected)
    assert "401" in message and "rejected" in message
    assert "sk-secret" not in message
    assert "sk-secret" not in describe_provider_error(RuntimeError("boom sk-secret-x"))
