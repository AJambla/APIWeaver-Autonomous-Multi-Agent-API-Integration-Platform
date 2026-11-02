"""Firebase ID token verification service.

Uses PyJWT with Google's public JWKS endpoint to verify Google / Firebase ID tokens
without extra heavy third-party dependencies (Ponytail mode).
"""

from __future__ import annotations

import logging
from typing import Any

import jwt
from jwt import PyJWKClient

from app.core.errors import UnauthenticatedError

logger = logging.getLogger(__name__)

GOOGLE_JWKS_URL = "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"

# Shared JWKS client with cache enabled to avoid fetching keys on every request.
_jwks_client: PyJWKClient | None = None


def get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(GOOGLE_JWKS_URL, cache_keys=True)
    return _jwks_client


def verify_firebase_id_token(
    id_token: str,
    *,
    project_id: str | None = None,
    jwks_client: PyJWKClient | None = None,
) -> dict[str, Any]:
    """Verify a Firebase ID token and return its decoded payload.

    Raises:
        UnauthenticatedError: If the token is invalid, expired, or failed signature checks.
    """
    if not id_token or not id_token.strip():
        raise UnauthenticatedError("Firebase ID token must not be empty.")

    client = jwks_client or get_jwks_client()

    try:
        signing_key = client.get_signing_key_from_jwt(id_token)
    except Exception as exc:
        logger.warning("Failed to retrieve signing key for Firebase token: %s", exc)
        raise UnauthenticatedError("Invalid Firebase token signing key.") from exc

    decode_kwargs: dict[str, Any] = {
        "algorithms": ["RS256"],
    }

    if project_id:
        decode_kwargs["audience"] = project_id
        decode_kwargs["issuer"] = f"https://securetoken.google.com/{project_id}"
    else:
        # If project_id is not set in config, bypass audience & issuer validation but enforce signature & expiry
        decode_kwargs["options"] = {"verify_aud": False, "verify_iss": False}

    try:
        payload = jwt.decode(id_token, signing_key.key, **decode_kwargs)
    except jwt.ExpiredSignatureError as exc:
        raise UnauthenticatedError("Firebase token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthenticatedError(f"Invalid Firebase token: {exc}") from exc

    if "sub" not in payload:
        raise UnauthenticatedError("Firebase token missing subject identifier.")

    return payload
