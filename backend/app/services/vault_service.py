"""HashiCorp Vault secret storage boundary (`Security.md §7`).

Credentials (OAuth client secrets, API tokens, webhook keys) are written directly to Vault
and never persisted in PostgreSQL or echoed in API responses (`API.md §6.3`).
`secrets_refs` in PostgreSQL stores only the Vault path pointer.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx
from fastapi import Depends
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter

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


def _is_transient_http_error(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {408, 429, 500, 502, 503, 504}
    return False

_vault_retry = retry(
    retry=retry_if_exception(_is_transient_http_error),
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(multiplier=0.1, max=1.5),
    reraise=True,
)


class HttpVaultClient:
    """Async Vault client speaking HTTP KV v2 to HashiCorp Vault."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.vault_addr = settings.vault_addr.rstrip("/")
        token = (settings.vault_token or "").strip()
        if not token:
            raise DependencyUnavailableError(
                "Vault token is required but VAULT_TOKEN is not configured."
            )
        self.vault_token = token
        self.vault_mount = getattr(settings, "vault_mount_path", "secret").strip("/")
        self.timeout = httpx.Timeout(10.0)
        self._headers = {"X-Vault-Token": self.vault_token}
        self._client = client
        self._owns_client = client is None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
            self._owns_client = True
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def __aenter__(self) -> HttpVaultClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()

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

    @_vault_retry
    async def write_secret(self, path: str, data: dict[str, Any]) -> None:
        url = self._kv_url(path)
        payload = {"data": data}
        client = self._get_client()
        try:
            response = await client.post(url, json=payload, headers=self._headers)
            response.raise_for_status()
        except Exception as exc:
            logger.error("vault_write_failed", path=path, error=str(exc))
            raise

    @_vault_retry
    async def read_secret(self, path: str) -> dict[str, Any] | None:
        url = self._kv_url(path)
        client = self._get_client()
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

    @_vault_retry
    async def delete_secret(self, path: str) -> None:
        url = self._kv_delete_url(path)
        client = self._get_client()
        try:
            response = await client.delete(url, headers=self._headers)
            if response.status_code not in (200, 204, 404):
                response.raise_for_status()
        except Exception as exc:
            logger.error("vault_delete_failed", path=path, error=str(exc))
            raise

    @_vault_retry
    async def renew_token(self, increment_seconds: int = 3600) -> bool:
        """Renew current Vault token lease."""
        url = f"{self.vault_addr}/v1/auth/token/renew-self"
        client = self._get_client()
        try:
            response = await client.post(
                url, json={"increment": f"{increment_seconds}s"}, headers=self._headers
            )
            return response.status_code == 200
        except Exception as exc:
            logger.warning("vault_token_renewal_failed", error=str(exc))
            return False


def create_vault_client(settings: Settings = Depends(get_settings)) -> VaultClient:
    return HttpVaultClient(settings)
