"""Health and readiness probes, plus the cross-cutting response contracts."""

from __future__ import annotations

from fastapi import FastAPI
from httpx import AsyncClient

from tests.conftest import FakeRedis


async def test_healthz_is_liveness_only(client: AsyncClient) -> None:
    """`/healthz` must not depend on Postgres or Redis.

    It is the ALB target-group check (`Architecture.md §11`); if it checked dependencies,
    a database blip would make every pod unhealthy at once and turn degradation into an
    outage.
    """
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readyz_reports_dependencies(client: AsyncClient) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"] == {"postgres": "ok", "redis": "ok"}


async def test_readyz_returns_503_when_a_dependency_is_down(
    app: FastAPI, client: AsyncClient, fake_redis: FakeRedis
) -> None:
    async def failing_ping() -> bool:
        raise ConnectionError("redis is down")

    fake_redis.ping = failing_ping  # type: ignore[method-assign]

    response = await client.get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["redis"] == "unavailable"
    # Postgres is still fine — the probe reports per-dependency, not just pass/fail.
    assert body["checks"]["postgres"] == "ok"


async def test_request_id_is_generated_and_echoed(client: AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.headers["X-Request-ID"].startswith("req_")


async def test_inbound_request_id_is_propagated(client: AsyncClient) -> None:
    """A trace started at the edge stays joined across services (`Deployment.md §11`)."""
    response = await client.get("/healthz", headers={"X-Request-ID": "req_from_edge"})
    assert response.headers["X-Request-ID"] == "req_from_edge"


async def test_oversized_inbound_request_id_is_replaced(client: AsyncClient) -> None:
    """An unbounded client-controlled id reaches logs, so it is capped."""
    response = await client.get("/healthz", headers={"X-Request-ID": "x" * 500})
    echoed = response.headers["X-Request-ID"]
    assert echoed != "x" * 500
    assert echoed.startswith("req_")


async def test_error_envelope_matches_api_spec(client: AsyncClient) -> None:
    """Every error uses the `API.md §5` shape, including FastAPI's own 404s."""
    response = await client.get("/api/v1/projects/not-a-uuid")
    assert response.status_code in (400, 401, 404)
    error = response.json()["error"]
    assert set(error) == {"code", "message", "details", "request_id"}
    assert error["request_id"]


async def test_validation_error_lists_offending_fields(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/login", json={"email": "not-an-email"})
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    fields = {detail["field"] for detail in error["details"]}
    assert "email" in fields
    assert "password" in fields


async def test_unknown_fields_are_rejected(client: AsyncClient) -> None:
    """`Security.md §10` — unknown fields rejected, not silently ignored."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "a@example.com", "password": "x" * 12, "is_admin": True},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_rate_limit_headers_present(client: AsyncClient) -> None:
    """`API.md §3` requires the trio on every response."""
    response = await client.post("/api/v1/auth/login", json={"email": "x", "password": "y"})
    for header in ("X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"):
        assert header in response.headers


async def test_healthz_is_exempt_from_rate_limiting(client: AsyncClient) -> None:
    """The load balancer polls this constantly; it must never be throttled."""
    for _ in range(150):
        assert (await client.get("/healthz")).status_code == 200
