"""HashiCorp Vault secret storage boundary (`Security.md §7`).

Credentials (OAuth client secrets, API tokens, webhook keys) are written directly to Vault
and never persisted in PostgreSQL or echoed in API responses (`API.md §6.3`).
`secrets_refs` in PostgreSQL stores only the Vault path pointer.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx
from fastapi import Depends

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class VaultClient(Protocol):
    async def write_secret(self, path: str, data: dict[str, Any]) -> None: ...

    async def read_secret(self, path: str) -> dict[str, Any] | None: ...

    async def delete_secret(self, path: str) -> None: ...


class HttpVaultClient:
    """Async Vault client speaking HTTP KV v2 to HashiCorp Vault."""

    def __init__(self, settings: Settings) -> None:
        self.vault_addr = settings.vault_addr.rstrip("/")
        self.vault_token = settings.vault_token or "root"
        self._headers = {"X-Vault-Token": self.vault_token}

    def _kv_url(self, path: str) -> str:
        clean_path = path.strip("/")
        if clean_path.startswith("secret/data/"):
            return f"{self.vault_addr}/v1/{clean_path}"
        if clean_path.startswith("secret/"):
            sub = clean_path[len("secret/"):]
            return f"{self.vault_addr}/v1/secret/data/{sub}"
        return f"{self.vault_addr}/v1/secret/data/{clean_path}"

    def _kv_delete_url(self, path: str) -> str:
        clean_path = path.strip("/")
        if clean_path.startswith("secret/metadata/"):
            return f"{self.vault_addr}/v1/{clean_path}"
        if clean_path.startswith("secret/"):
            sub = clean_path[len("secret/"):]
            return f"{self.vault_addr}/v1/secret/metadata/{sub}"
        return f"{self.vault_addr}/v1/secret/metadata/{clean_path}"

    async def write_secret(self, path: str, data: dict[str, Any]) -> None:
        url = self._kv_url(path)
        payload = {"data": data}
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(url, json=payload, headers=self._headers)
                response.raise_for_status()
            except Exception as exc:
                logger.error("vault_write_failed", path=path, error=str(exc))
                raise

    async def read_secret(self, path: str) -> dict[str, Any] | None:
        url = self._kv_url(path)
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(url, headers=self._headers)
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                body = response.json()
                # KV v2 wraps data inside {"data": {"data": {...}}}
                data = body.get("data", {}).get("data")
                return dict(data) if isinstance(data, dict) else None
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return None
                logger.error("vault_read_failed", path=path, error=str(exc))
                raise
            except Exception as exc:
                logger.error("vault_read_failed", path=path, error=str(exc))
                raise

    async def delete_secret(self, path: str) -> None:
        url = self._kv_delete_url(path)
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.delete(url, headers=self._headers)
                if response.status_code not in (200, 204, 404):
                    response.raise_for_status()
            except Exception as exc:
                logger.error("vault_delete_failed", path=path, error=str(exc))
                raise


class FakeVaultClient:
    """In-memory mock Vault client for testing."""

    def __init__(self) -> None:
        self._secrets: dict[str, dict[str, Any]] = {}

    async def write_secret(self, path: str, data: dict[str, Any]) -> None:
        self._secrets[path.strip("/")] = dict(data)

    async def read_secret(self, path: str) -> dict[str, Any] | None:
        data = self._secrets.get(path.strip("/"))
        return dict(data) if data is not None else None

    async def delete_secret(self, path: str) -> None:
        self._secrets.pop(path.strip("/"), None)


# Module-level singleton (export_agent.py uses this)
# Use create_vault_client() with settings in production; this is a lazy class reference.
vault_service = HttpVaultClient


def create_vault_client(settings: Settings = Depends(get_settings)) -> VaultClient:
    return HttpVaultClient(settings)
