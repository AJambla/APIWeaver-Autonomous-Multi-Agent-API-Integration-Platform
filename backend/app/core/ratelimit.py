"""Rate limiting (`Security.md §9`, `API.md §3`, key pattern from `Database.md §7`).

Two layers, because they defend different things:

1. `RateLimitMiddleware` — coarse, per-IP, applies before authentication. This is what
   protects `POST /auth/login` from credential stuffing (`Security.md §8`, A07), which a
   post-authentication limiter by definition cannot do.
2. `enforce_org_rate_limit` — a dependency on authenticated routes, keyed by organization
   and scaled to its `plan_tier` per the `API.md §3` table. It needs the resolved
   principal, so it cannot live in middleware.

Both fail **open** if Redis is unreachable. That tradeoff is deliberate: Redis is a cache,
not the system of record, and taking the entire API down because the limiter cannot count
would turn a degraded dependency into an outage.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import redis.asyncio as aioredis
from fastapi import Depends, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.deps import get_current_principal, get_db, get_redis
from app.core.errors import ErrorCode, build_error_body
from app.core.logging import get_logger
from app.models.organization import Organization
from app.rbac.policy import Principal

logger = get_logger(__name__)

WINDOW_SECONDS = 60

# Requests/min per plan tier — `API.md §3`. Enterprise is documented as "Custom"; until
# per-org overrides exist it takes the Pro ceiling rather than being treated as unlimited,
# so a misconfigured enterprise org still cannot exhaust the cluster.
TIER_REQUESTS_PER_MINUTE: dict[str, int] = {
    "free": 60,
    "pro": 600,
    "enterprise": 600,
}

# Unauthenticated per-IP budget. Deliberately generous relative to the Free tier: one IP
# can legitimately be a whole office behind NAT, so this is an abuse ceiling, not a
# fairness quota.
ANONYMOUS_REQUESTS_PER_MINUTE = 120

# Probes are polled constantly by the load balancer and carry no credential to attribute
# to an org, so they are exempt (`Architecture.md §11`).
EXEMPT_PATHS = frozenset({"/healthz", "/readyz", "/metrics"})


@dataclass(frozen=True, slots=True)
class Verdict:
    allowed: bool
    limit: int
    remaining: int
    reset_at: int

    @property
    def retry_after(self) -> int:
        return max(1, self.reset_at - int(time.time()))

    def headers(self) -> dict[str, str]:
        """The `X-RateLimit-*` trio required on every response by `API.md §3`."""
        return {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(self.remaining),
            "X-RateLimit-Reset": str(self.reset_at),
        }


async def consume(redis_client: aioredis.Redis, identity: str, limit: int) -> Verdict:
    """Count one request against `identity`'s current window.

    Fixed-window counter under the `ratelimit:{identity}:{window}` pattern from
    `Database.md §7`. A true sliding window needs a sorted set per identity and a ZREMRANGE
    on every request; the fixed window is a single pipelined INCR and is accurate enough
    for abuse prevention, at the cost of allowing up to 2x the limit across a window
    boundary. That burst is acceptable here and is not for the quota-billing path.

    Returns an allow-verdict on Redis failure (fail open).
    """
    window = int(time.time()) // WINDOW_SECONDS
    reset_at = (window + 1) * WINDOW_SECONDS
    key = f"ratelimit:{identity}:{window}"

    try:
        pipe = redis_client.pipeline()
        pipe.incr(key)
        # Outlive the window it counts, but not by much.
        pipe.expire(key, WINDOW_SECONDS + 5)
        results = await pipe.execute()
        current = int(results[0])
    except Exception as exc:  # noqa: BLE001 — fail open, see module docstring
        logger.warning("rate_limit_unavailable", error=str(exc), identity=identity)
        return Verdict(allowed=True, limit=limit, remaining=limit, reset_at=reset_at)

    return Verdict(
        allowed=current <= limit,
        limit=limit,
        remaining=max(0, limit - current),
        reset_at=reset_at,
    )


def _client_identity(request: Request) -> str:
    """Pre-auth identity: the API key's hash if present, else the client IP.

    The key is hashed so a credential never reaches a Redis key name or a log line.
    """
    if api_key := request.headers.get("x-api-key"):
        from app.core.security import hash_opaque_token

        return f"key:{hash_opaque_token(api_key)[:16]}"

    # X-Forwarded-For because the ALB terminates TLS (`Architecture.md §11`).
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return f"ip:{forwarded.split(',')[0].strip()}"
    return f"ip:{request.client.host if request.client else 'unknown'}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Pre-authentication per-IP limiting.

    Returns a `JSONResponse` directly rather than raising. Exceptions raised inside
    `BaseHTTPMiddleware` are not seen by the app's registered exception handlers — the
    handler middleware sits *inside* user middleware — so raising here would surface as a
    bare 500 instead of the `API.md §5` error envelope.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        redis_client: aioredis.Redis | None = getattr(request.app.state, "redis", None)
        if redis_client is None:
            return await call_next(request)

        verdict = await consume(
            redis_client, _client_identity(request), ANONYMOUS_REQUESTS_PER_MINUTE
        )

        if not verdict.allowed:
            logger.info("rate_limit_exceeded", scope="ip", path=request.url.path)
            return JSONResponse(
                status_code=429,
                content=build_error_body(
                    code=ErrorCode.RATE_LIMIT_EXCEEDED,
                    message="Too many requests. Please retry later.",
                    request_id=getattr(request.state, "request_id", ""),
                ),
                headers={
                    "Retry-After": str(verdict.retry_after),
                    **verdict.headers(),
                },
            )

        response = await call_next(request)
        # setdefault semantics: the org-tier limiter runs later in the stack and its
        # numbers are the meaningful ones, so don't clobber headers it already set.
        for header, value in verdict.headers().items():
            if header not in response.headers:
                response.headers[header] = value
        return response


async def enforce_org_rate_limit(
    response: Response,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> None:
    """Per-organization, tier-scaled limiting for authenticated routes (`API.md §3`)."""
    if principal.organization_id is None:
        return

    plan_tier = await session.scalar(
        select(Organization.plan_tier).where(Organization.id == principal.organization_id)
    )
    limit = TIER_REQUESTS_PER_MINUTE.get(plan_tier or "", TIER_REQUESTS_PER_MINUTE["free"])

    verdict = await consume(redis_client, f"org:{principal.organization_id}", limit)

    # Set on the success path too — API.md §3 says these appear on every response.
    for header, value in verdict.headers().items():
        response.headers[header] = value

    if not verdict.allowed:
        logger.info(
            "rate_limit_exceeded",
            scope="organization",
            organization_id=str(principal.organization_id),
            path=request.url.path,
            limit=limit,
        )
        from app.core.errors import RateLimitExceededError

        raise RateLimitExceededError(verdict.retry_after, headers=verdict.headers())
