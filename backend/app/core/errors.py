"""Error taxonomy and the standard error envelope from `API.md §5`.

Every error response the platform emits has the shape:

    {"error": {"code", "message", "details", "request_id"}}

`APIError` carries the machine-readable `code` alongside the HTTP status so handlers
never have to infer one from the other.
"""

from __future__ import annotations

from typing import Any


class ErrorCode:
    """Machine-readable error codes. Stable identifiers — clients switch on these."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    TOKEN_REVOKED = "TOKEN_REVOKED"
    TOKEN_REUSE_DETECTED = "TOKEN_REUSE_DETECTED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    UNPROCESSABLE_ENTITY = "UNPROCESSABLE_ENTITY"
    UNPARSEABLE_DOCUMENT = "UNPARSEABLE_DOCUMENT"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"


class APIError(Exception):
    """Base for all deliberately-raised API errors."""

    status_code: int = 500
    code: str = ErrorCode.INTERNAL_ERROR
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or self.message
        self.details = details or []
        self.headers = headers or {}
        super().__init__(self.message)


class ValidationError(APIError):
    status_code = 400
    code = ErrorCode.VALIDATION_ERROR
    message = "The request payload is invalid."


class UnauthenticatedError(APIError):
    status_code = 401
    code = ErrorCode.UNAUTHENTICATED
    message = "Authentication is required."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        if code is not None:
            self.code = code
        # WWW-Authenticate is required on 401 by RFC 9110.
        super().__init__(message, details=details, headers={"WWW-Authenticate": "Bearer"})


class ForbiddenError(APIError):
    status_code = 403
    code = ErrorCode.FORBIDDEN
    message = "You do not have permission to perform this action."


class NotFoundError(APIError):
    status_code = 404
    code = ErrorCode.NOT_FOUND
    message = "The requested resource does not exist."


class ConflictError(APIError):
    status_code = 409
    code = ErrorCode.CONFLICT
    message = "The request conflicts with the current state of the resource."


class UnprocessableEntityError(APIError):
    status_code = 422
    code = ErrorCode.UNPROCESSABLE_ENTITY
    message = "The request was well-formed but semantically invalid."


class RateLimitExceededError(APIError):
    status_code = 429
    code = ErrorCode.RATE_LIMIT_EXCEEDED
    message = "Rate limit exceeded."

    def __init__(self, retry_after_seconds: int, *, headers: dict[str, str] | None = None) -> None:
        merged = {"Retry-After": str(retry_after_seconds), **(headers or {})}
        super().__init__(headers=merged)


class DependencyUnavailableError(APIError):
    """503 — a downstream dependency (LLM provider, Vault, S3) is unreachable."""

    status_code = 503
    code = ErrorCode.DEPENDENCY_UNAVAILABLE
    message = "A downstream dependency is currently unavailable."


def build_error_body(
    *,
    code: str,
    message: str,
    request_id: str,
    details: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Render the `API.md §5` envelope."""
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or [],
            "request_id": request_id,
        }
    }
