"""Request correlation middleware.

Rate limiting lives in `app/core/ratelimit.py` — it needs both a middleware and a
dependency layer, so it earns its own module.
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import ErrorCode, build_error_body
from app.core.logging import get_logger, request_id_ctx

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"

# An inbound id is echoed into logs and error bodies, so it is length- and
# charset-capped: an unbounded client-controlled string is a log-injection vector.
MAX_INBOUND_REQUEST_ID_LENGTH = 64
SAFE_REQUEST_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.:=]{1,64}$")


def is_valid_request_id(request_id: str) -> bool:
    """Validate that an inbound request ID is safe, bounded, and free of injection vectors."""
    if not request_id or len(request_id) > MAX_INBOUND_REQUEST_ID_LENGTH:
        return False
    return bool(SAFE_REQUEST_ID_PATTERN.fullmatch(request_id))


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Assign or propagate `request_id` (`Deployment.md §11`).

    An inbound `X-Request-ID` is honoured so a trace started at the edge stays joined
    across services; anything unusable is replaced with a generated id.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        inbound = request.headers.get(REQUEST_ID_HEADER, "")
        if is_valid_request_id(inbound):
            request_id = inbound
        else:
            request_id = f"req_{uuid.uuid4().hex[:12]}"

        # Set on state before the contextvar so exception handlers can read it even if
        # the contextvar has already been reset.
        request.state.request_id = request_id
        token = request_id_ctx.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            # Logged before the context var is reset, so the access line carries it.
            logger.info(
                "request_completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            return response
        finally:
            request_id_ctx.reset(token)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Enforce standard HTTP security response headers across all endpoints."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-XSS-Protection", "1; mode=block")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; frame-ancestors 'none'; object-src 'none'",
        )
        response.headers.setdefault(
            "Permissions-Policy",
            "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()",
        )
        return response



# Room for multipart boundaries and form fields around a max-size file.
_MULTIPART_OVERHEAD_BYTES = 1024 * 1024
# Every non-upload route takes small JSON bodies.
MAX_JSON_BODY_BYTES = 2 * 1024 * 1024


class BodySizeLimitMiddleware:
    """Refuse request bodies larger than the route could ever accept.

    The upload route checked `max_upload_bytes` only after Starlette had already spooled
    the whole multipart body to disk, and nothing bounded JSON bodies at all; only nginx's
    client_max_body_size stood in front, which does not apply when the API is reached
    directly or through the ALB. A declared Content-Length over the limit is refused
    before reading; a chunked body is counted as it streams.
    """

    def __init__(self, app: ASGIApp, *, max_upload_bytes: int) -> None:
        self.app = app
        self.max_upload_bytes = max_upload_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        limit = (
            self.max_upload_bytes + _MULTIPART_OVERHEAD_BYTES
            if headers.get("content-type", "").startswith("multipart/form-data")
            else MAX_JSON_BODY_BYTES
        )
        declared = headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            response = JSONResponse(
                status_code=413,
                content=build_error_body(
                    code=ErrorCode.PAYLOAD_TOO_LARGE,
                    message="The request body is larger than this endpoint accepts.",
                    request_id=scope.get("state", {}).get("request_id", ""),
                ),
            )
            await response(scope, receive, send)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # An HTTPException: FastAPI's body parsing re-raises these unchanged
                    # (anything else becomes a generic 400 "error parsing the body").
                    raise HTTPException(
                        status_code=413,
                        detail="The request body is larger than this endpoint accepts.",
                    )
            return message

        await self.app(scope, limited_receive, send)
