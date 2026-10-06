"""Tests for security hardening and multi-tenancy protections."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services.ingestion_service import sanitize_filename
from app.services.sandbox_service import create_sandbox_client
from app.services.storage_service import InMemoryObjectStorage, validate_storage_key
from app.services.vault_service import FakeVaultClient, validate_vault_path


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

    def test_create_sandbox_client_raises_in_production_if_not_docker(
        self, test_settings: Settings
    ) -> None:
        settings = _make_settings(test_settings, app_env="production", sandbox_backend="docker")
        object.__setattr__(settings, "sandbox_backend", "mock")
        with pytest.raises(RuntimeError, match="cannot be used in production mode"):
            create_sandbox_client(settings)

    def test_create_sandbox_client_raises_in_staging_if_not_docker(
        self, test_settings: Settings
    ) -> None:
        settings = _make_settings(test_settings, app_env="staging", sandbox_backend="docker")
        object.__setattr__(settings, "sandbox_backend", "mock")
        with pytest.raises(RuntimeError, match="cannot be used in staging mode"):
            create_sandbox_client(settings)



class TestStorageKeyValidation:
    """Ensure storage operations reject path traversal."""

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
