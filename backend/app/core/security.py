"""Cryptographic primitives: password hashing, JWT sign/verify, opaque token minting.

Implements `Security.md §1` (Argon2id passwords, rotating refresh tokens), `§4` (RS256
JWT with the exact claim set), and `§5` (API key format and hashed storage).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import Settings, get_settings

# --- Passwords ----------------------------------------------------------------------
# Explicit parameters rather than library defaults so the work factor is a reviewable
# constant. These target roughly 50-100ms per hash on the API node class in
# Deployment.md §7 (m6i.xlarge) and follow the OWASP Argon2id recommendation.
_password_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,  # 64 MiB
    parallelism=4,
    hash_len=32,
    salt_len=16,
)

# Minimum password length. Breached-password checking (Security.md §8, A07) needs an
# external corpus and lands with the full signup hardening pass.
MIN_PASSWORD_LENGTH = 12


def hash_password(password: str) -> str:
    """Hash a password with Argon2id. The returned string embeds salt and parameters."""
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Constant-time-ish password check.

    A `None` hash (SSO-only account, per `Database.md §3.2`) still burns a hash
    computation so a caller cannot distinguish "no password set" from "wrong password"
    by response timing.
    """
    if password_hash is None:
        _password_hasher.hash(password)
        return False
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """True when the stored hash predates the current work factor."""
    return _password_hasher.check_needs_rehash(password_hash)


# --- Opaque tokens (refresh tokens, API keys) ---------------------------------------
# These are high-entropy random secrets, not passwords. SHA-256 is the right primitive:
# there is no offline-guessing threat model for 256 bits of entropy, and we need a
# deterministic hash so the value is directly indexable for lookup.

REFRESH_TOKEN_BYTES = 32
API_KEY_BYTES = 32
API_KEY_LIVE_PREFIX = "apw_live_"
API_KEY_TEST_PREFIX = "apw_test_"


def generate_opaque_token(num_bytes: int = REFRESH_TOKEN_BYTES) -> str:
    return secrets.token_urlsafe(num_bytes)


def hash_opaque_token(token: str) -> str:
    """SHA-256 hex digest — 64 chars, matching the `CHAR(64)` storage columns."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_opaque_token(token: str, token_hash: str) -> bool:
    return hmac.compare_digest(hash_opaque_token(token), token_hash)


@dataclass(frozen=True, slots=True)
class GeneratedAPIKey:
    """A freshly minted API key. `plaintext` is returned to the user exactly once."""

    plaintext: str
    prefix: str
    key_hash: str


def generate_api_key(*, live: bool = True) -> GeneratedAPIKey:
    """Mint an API key in the `Security.md §5` format: `apw_live_<random>`."""
    prefix = API_KEY_LIVE_PREFIX if live else API_KEY_TEST_PREFIX
    plaintext = f"{prefix}{secrets.token_urlsafe(API_KEY_BYTES)}"
    return GeneratedAPIKey(
        plaintext=plaintext,
        prefix=prefix,
        key_hash=hash_opaque_token(plaintext),
    )


# --- JWT ----------------------------------------------------------------------------


class JWTError(Exception):
    """Raised for any token that fails to verify. Deliberately does not distinguish
    signature failure from malformed input to the caller beyond the `code`."""

    def __init__(self, message: str, *, expired: bool = False) -> None:
        self.expired = expired
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class _KeyPair:
    private_key: str
    public_key: str


@lru_cache(maxsize=1)
def _load_keys(private_path: Path, public_path: Path) -> _KeyPair:
    """Read the RS256 keypair from disk once.

    Keys live on the filesystem (mounted from Vault in production per
    `Deployment.md §9`), never in env vars or source.
    """
    try:
        private_key = private_path.read_text(encoding="utf-8")
        public_key = public_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(
            f"unable to read JWT keypair ({private_path}, {public_path}); "
            "run scripts/gen_jwt_keys.sh for local development"
        ) from exc
    return _KeyPair(private_key=private_key, public_key=public_key)


def load_keys(settings: Settings | None = None) -> _KeyPair:
    settings = settings or get_settings()
    return _load_keys(settings.jwt_private_key_path, settings.jwt_public_key_path)


@dataclass(frozen=True, slots=True)
class AccessToken:
    token: str
    jti: str
    expires_at: datetime
    expires_in: int


def create_access_token(
    *,
    user_id: uuid.UUID,
    org_id: uuid.UUID | None,
    role: str | None,
    settings: Settings | None = None,
) -> AccessToken:
    """Mint an RS256 access token with exactly the `Security.md §4` claim set."""
    settings = settings or get_settings()
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    jti = str(uuid.uuid4())

    claims: dict[str, Any] = {
        "sub": str(user_id),
        "org_id": str(org_id) if org_id else None,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": jti,
        "iss": settings.jwt_issuer,
    }

    token = jwt.encode(
        claims,
        load_keys(settings).private_key,
        algorithm=settings.jwt_algorithm,
    )
    return AccessToken(
        token=token,
        jti=jti,
        expires_at=expires_at,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


def decode_access_token(token: str, settings: Settings | None = None) -> dict[str, Any]:
    """Verify signature, expiry, and issuer.

    `algorithms` is pinned to the single configured algorithm — accepting a list the
    attacker can influence is the classic JWT algorithm-confusion bug.
    """
    settings = settings or get_settings()
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            load_keys(settings).public_key,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            options={"require": ["sub", "exp", "iat", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise JWTError("access token has expired", expired=True) from exc
    except jwt.InvalidTokenError as exc:
        raise JWTError("access token is invalid") from exc
    return claims
