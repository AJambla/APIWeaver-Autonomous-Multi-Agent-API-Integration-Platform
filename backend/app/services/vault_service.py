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
from app.core.errors import DependencyUnavailableError
from app.core.logging import get_logger

logger = get_logger(__name__)


class VaultClient(Protocol):
    async def write_secret(self, path: str, data: dict[str, Any]) -> None: ...

    async def read_secret(self, path: str) -> dict[str, Any] | None: ...

    async def delete_secret(self, path: str) -> None: ...

    async def renew_token(self, increment_seconds: int = 3600) -> bool: ...


def validate_vault_path(path: str) -> str:
    """Validate Vault path to prevent path traversal."""
    if not isinstance(path, str):
        raise ValueError("Vault path must be a string")
    cleaned = path.strip().replace("\\", "/").strip("/")
    parts = cleaned.split("/")
    if any(part in ("..", ".") for part in parts) or not cleaned:
        raise ValueError(f"Path traversal or empty path not permitted in Vault path: {path}")
    return cleaned


class HttpVaultClient:
    """Async Vault client speaking HTTP KV v2 to HashiCorp Vault."""

    def __init__(self, settings: Settings) -> None:
        self.vault_addr = settings.vault_addr.rstrip("/")
        token = (settings.vault_token or "").strip()
        if not token:
            raise DependencyUnavailableError(
                "Vault token is required but VAULT_TOKEN is not configured."
            )
        self.vault_token = token
        self.vault_mount = getattr(settings, "vault_mount_path", "secret").strip("/")
        self._headers = {"X-Vault-Token": self.vault_token}

    def _kv_url(self, path: str) -> str:
        clean_path = validate_vault_path(path)
        mount = self.vault_mount
        if clean_path.startswith(f"{mount}/data/") or clean_path.startswith("secret/data/"):
            return f"{self.vault_addr}/v1/{clean_path}"
        if clean_path.startswith(f"{mount}/"):
            sub = clean_path[len(f"{mount}/"):]
            return f"{self.vault_addr}/v1/{mount}/data/{sub}"
        if clean_path.startswith("secret/"):
            sub = clean_path[len("secret/"):]
            return f"{self.vault_addr}/v1/{mount}/data/{sub}"
        return f"{self.vault_addr}/v1/{mount}/data/{clean_path}"

    def _kv_delete_url(self, path: str) -> str:
        clean_path = validate_vault_path(path)
        mount = self.vault_mount
        if clean_path.startswith(f"{mount}/metadata/") or clean_path.startswith("secret/metadata/"):
            return f"{self.vault_addr}/v1/{clean_path}"
        if clean_path.startswith(f"{mount}/"):
            sub = clean_path[len(f"{mount}/"):]
            return f"{self.vault_addr}/v1/{mount}/metadata/{sub}"
        if clean_path.startswith("secret/"):
            sub = clean_path[len("secret/"):]
            return f"{self.vault_addr}/v1/{mount}/metadata/{sub}"
        return f"{self.vault_addr}/v1/{mount}/metadata/{clean_path}"

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

    async def renew_token(self, increment_seconds: int = 3600) -> bool:
        """Renew current Vault token lease (/v1/auth/token/renew-self)."""
        url = f"{self.vault_addr}/v1/auth/token/renew-self"
        payload = {"increment": f"{increment_seconds}s"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(url, json=payload, headers=self._headers)
                if response.status_code in (200, 204):
                    logger.info("vault_token_renewed", increment=increment_seconds)
                    return True
                logger.warning("vault_token_renewal_rejected", status_code=response.status_code)
                return False
            except Exception as exc:
                logger.warning("vault_token_renewal_failed", error=str(exc))
                return False




def create_vault_client(settings: Settings = Depends(get_settings)) -> VaultClient:
    return HttpVaultClient(settings)
