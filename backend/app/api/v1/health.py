"""Liveness and readiness probes.

`/healthz` is the target-group health check in `Architecture.md §11` and the Dockerfile
`HEALTHCHECK`. It answers "is this process alive", nothing more — deliberately not
checking Postgres or Redis, because a database blip should not cause the load balancer to
evict every healthy pod at once and turn a degraded dependency into a full outage.

`/readyz` is the stricter check: it verifies dependencies and is what a rolling deploy or
a Kubernetes readiness probe should gate traffic on.
"""

from __future__ import annotations

from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_redis
from app.core.logging import get_logger

router = APIRouter(tags=["health"])
logger = get_logger(__name__)


@router.get("/healthz", summary="Liveness probe")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", summary="Readiness probe")
async def readyz(
    response: Response,
    session: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> dict[str, Any]:
    """503 unless every hard dependency answers."""
    checks: dict[str, str] = {}

    try:
        # `SELECT 1` is a static literal, not built from input — no injection surface.
        await session.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:  # noqa: BLE001 — a probe reports, it never propagates
        logger.warning("readiness_check_failed", dependency="postgres", error=str(exc))
        checks["postgres"] = "unavailable"

    try:
        await redis_client.ping()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        logger.warning("readiness_check_failed", dependency="redis", error=str(exc))
        checks["redis"] = "unavailable"

    ready = all(state == "ok" for state in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ready else "not_ready", "checks": checks}
