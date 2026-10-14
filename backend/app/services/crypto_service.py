"""AES-256-GCM authenticated credential encryption and secret storage service.

Replaces HashiCorp Vault with zero-dependency authenticated symmetric encryption
(NIST SP 800-38D). Credentials (API keys, OAuth tokens) are encrypted at rest
and never logged or exposed in prompts.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import Depends

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def validate_secret_path(path: str) -> str:
    """Validate secret path to prevent directory traversal or malformed paths."""
    if not isinstance(path, str):
        raise ValueError("Secret path must be a string")
    cleaned = path.strip().replace("\\", "/").strip("/")
    parts = cleaned.split("/")
    if any(part in ("..", ".") for part in parts) or not cleaned:
        raise ValueError(f"Path traversal or empty path not permitted in secret path: {path}")
    return cleaned


# Backward-compatible alias
validate_vault_path = validate_secret_path


class SecretClient(Protocol):
    async def write_secret(self, path: str, data: dict[str, Any]) -> None: ...
    async def read_secret(self, path: str) -> dict[str, Any] | None: ...
    async def delete_secret(self, path: str) -> None: ...
    async def renew_token(self, increment_seconds: int = 3600) -> bool: ...


class CryptoService:
    """AES-256-GCM authenticated encryption and secret storage client."""

    def __init__(
        self,
        key: bytes | None = None,
        storage_dir: str | Path | None = None,
    ) -> None:
        if key is None:
            # Deterministic dev fallback key if not provided
            key = hashlib.sha256(b"apiweaver-default-insecure-dev-encryption-key").digest()
        elif len(key) != 32:
            # Derive 32-byte key via SHA-256
            key = hashlib.sha256(key).digest()

        self._key = key
        self._aesgcm = AESGCM(self._key)
        self._storage_dir = Path(storage_dir or "./storage/secrets").resolve()
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def encrypt(self, data: dict[str, Any] | str | bytes) -> str:
        """Encrypt payload using AES-256-GCM with a fresh 12-byte nonce."""
        if isinstance(data, dict):
            raw_bytes = json.dumps(data).encode("utf-8")
        elif isinstance(data, str):
            raw_bytes = data.encode("utf-8")
        elif isinstance(data, bytes):
            raw_bytes = data
        else:
            raw_bytes = str(data).encode("utf-8")

        nonce = os.urandom(12)
        ciphertext = self._aesgcm.encrypt(nonce, raw_bytes, None)
        # Store as base64-urlsafe string: nonce (12B) + ciphertext + auth tag (16B)
        combined = nonce + ciphertext
        return base64.urlsafe_b64encode(combined).decode("utf-8")

    def decrypt(self, token: str) -> Any:
        """Decrypt AES-256-GCM ciphertext string."""
        raw = base64.urlsafe_b64decode(token.encode("utf-8"))
        if len(raw) < 28:  # 12-byte nonce + 16-byte tag minimum
            raise ValueError("Ciphertext is too short to be valid AES-GCM data")

        nonce = raw[:12]
        ciphertext = raw[12:]
        plaintext_bytes = self._aesgcm.decrypt(nonce, ciphertext, None)
        plaintext = plaintext_bytes.decode("utf-8")

        try:
            return json.loads(plaintext)
        except Exception:
            return plaintext

    def _resolve_path(self, path: str) -> Path:
        safe_path = validate_secret_path(path)
        target = (self._storage_dir / safe_path).resolve()
        if not str(target).startswith(str(self._storage_dir)):
            raise ValueError(f"Path traversal detected: {path}")
        return target

    async def write_secret(self, path: str, data: dict[str, Any]) -> None:
        """Store an encrypted secret under the given path."""
        target = self._resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        encrypted_token = self.encrypt(data)
        target.write_text(encrypted_token, encoding="utf-8")
        logger.info("secret_written_encrypted", path=path)

    async def read_secret(self, path: str) -> dict[str, Any] | None:
        """Retrieve and decrypt secret stored at the given path."""
        target = self._resolve_path(path)
        if not target.is_file():
            return None
        token = target.read_text(encoding="utf-8").strip()
        data = self.decrypt(token)
        if isinstance(data, dict):
            return data
        return {"value": data}

    async def delete_secret(self, path: str) -> None:
        """Delete secret at the given path."""
        target = self._resolve_path(path)
        if target.is_file():
            target.unlink()
            logger.info("secret_deleted", path=path)

    async def renew_token(self, increment_seconds: int = 3600) -> bool:
        """No-op token renewal to satisfy legacy VaultClient protocol."""
        return True


# Global singleton
_crypto_instance: CryptoService | None = None


def create_crypto_service(settings: Settings = Depends(get_settings)) -> CryptoService:
    global _crypto_instance
    if _crypto_instance is None:
        encryption_key = getattr(settings, "app_encryption_key", None)
        key_bytes = encryption_key.encode("utf-8") if encryption_key else None
        storage_dir = Path(getattr(settings, "storage_local_dir", "./storage")) / "secrets"
        _crypto_instance = CryptoService(key=key_bytes, storage_dir=storage_dir)
    return _crypto_instance


# Backward compatibility aliases
VaultClient = SecretClient
HttpVaultClient = CryptoService
create_vault_client = create_crypto_service
