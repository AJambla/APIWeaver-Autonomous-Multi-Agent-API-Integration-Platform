"""Liveness and readiness probes.

`/healthz` is the target-group health check in `Architecture.md §11` and the Dockerfile
`HEALTHCHECK`. It answers "is this process alive", nothing more — deliberately not
checking Postgres or Redis, because a database blip should not cause the load balancer to
evict every healthy pod at once and turn a degraded dependency into a full outage.

`/readyz` is the stricter check: it verifies dependencies and is what a rolling deploy or
a Kubernetes readiness probe should gate traffic on.
"""

from __future__ import annotations

import time
from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.deps import get_current_principal, get_db, get_redis
from app.core.logging import get_logger
from app.rbac.enforce import require_own_org_permission
from app.rbac.policy import Permission, Principal
from app.workflows.llm import LLMClient, active_llm_model

router = APIRouter(tags=["health"])
# Authenticated, rate-limited LLM endpoints, mounted only under /api/v1 (`router.py`):
# they reveal provider configuration and one of them spends tokens.
llm_router = APIRouter(tags=["health"])
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


@llm_router.get("/health/llm", summary="LLM configuration status")
async def health_llm(
    _principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    """Report configured LLM provider, model, and whether credentials exist."""
    settings = get_settings()
    provider = "anthropic" if settings.anthropic_api_key and not settings.openai_api_key else "openai"
    is_configured = bool(settings.openai_api_key or settings.anthropic_api_key)
    return {
        "provider": provider,
        "model": active_llm_model(settings),
        "base_url": settings.openai_api_base_url,
        "is_configured": is_configured,
    }


@llm_router.post("/health/llm/test", summary="Test LLM connection")
async def test_llm_connection(
    _principal: Principal = Depends(require_own_org_permission(Permission.ORG_MANAGE_API_KEYS)),
) -> dict[str, Any]:
    """Dispatches a real (billed) LLM call, so it is limited to org admins and sits behind
    the org rate limiter (`router.py`)."""
    """Test LLM connectivity by dispatching a lightweight prompt and returning latency."""
    settings = get_settings()
    client = LLMClient(settings=settings)
    start = time.perf_counter()
    try:
        result, token_count = await client.generate_json(
            system_prompt="You are a health check probe. Return strict JSON only.",
            user_prompt='Return a JSON object: {"status": "ok", "message": "LLM connection active"}',
        )
        latency_ms = int((time.perf_counter() - start) * 1000)
        return {
            "status": "ok",
            "latency_ms": latency_ms,
            "model": active_llm_model(settings),
            "tokens": token_count,
            "payload": result,
        }
    except Exception as exc:
        latency_ms = int((time.perf_counter() - start) * 1000)
        logger.warning("llm_health_check_failed", error=str(exc))
        return {
            "status": "error",
            "latency_ms": latency_ms,
            "model": active_llm_model(settings),
            "error": str(exc),
        }

