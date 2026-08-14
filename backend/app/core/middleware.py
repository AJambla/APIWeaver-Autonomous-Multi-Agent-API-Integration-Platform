"""Request correlation middleware.

Rate limiting lives in `app/core/ratelimit.py` — it needs both a middleware and a
dependency layer, so it earns its own module.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger, request_id_ctx

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"

# An inbound id is echoed into logs and error bodies, so it is length- and
# charset-capped: an unbounded client-controlled string is a log-injection vector.
MAX_INBOUND_REQUEST_ID_LENGTH = 64


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Assign or propagate `request_id` (`Deployment.md §11`).

    An inbound `X-Request-ID` is honoured so a trace started at the edge stays joined
    across services; anything unusable is replaced with a generated id.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        inbound = request.headers.get(REQUEST_ID_HEADER, "")
        if inbound and len(inbound) <= MAX_INBOUND_REQUEST_ID_LENGTH and inbound.isprintable():
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
        finally:
            request_id_ctx.reset(token)

        response.headers[REQUEST_ID_HEADER] = request_id
        logger.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return response
