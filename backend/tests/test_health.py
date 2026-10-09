"""Health and readiness probes, plus the cross-cutting response contracts."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app
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


async def test_unsafe_inbound_request_id_is_replaced(client: AsyncClient) -> None:
    """Inbound IDs with injection chars, quotes, spaces, or script tags are replaced."""
    unsafe_ids = [
        'req"injection',
        "req with spaces",
        "<script>alert(1)</script>",
        "req; DROP TABLE audit_logs;",
        "req\nnewline",
    ]
    for bad_id in unsafe_ids:
        response = await client.get("/healthz", headers={"X-Request-ID": bad_id})
        echoed = response.headers["X-Request-ID"]
        assert echoed != bad_id, f"Expected {bad_id} to be rejected"
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


@asynccontextmanager
async def _client_for(settings: Settings) -> AsyncIterator[AsyncClient]:
    """A client over an app built from a settings variant.

    `/metrics` wiring depends on `app_env` and `METRICS_TOKEN`, which the shared dev
    fixture cannot express. These probes build their own app instead.
    """
    transport = ASGITransport(app=create_app(settings))
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http


async def test_metrics_requires_the_configured_token(test_settings: Settings) -> None:
    scoped = test_settings.model_copy(update={"metrics_token": "scrape-token"})
    async with _client_for(scoped) as http:
        anonymous = await http.get("/metrics")
        assert anonymous.status_code == 401
        assert anonymous.json()["error"]["code"] == "UNAUTHENTICATED"

        authorized = await http.get(
            "/metrics", headers={"X-Metrics-Token": "scrape-token"}
        )
        assert authorized.status_code == 200
        assert "# HELP apiweaver_auth_success_total" in authorized.text


async def test_metrics_rejects_a_wrong_token(test_settings: Settings) -> None:
    scoped = test_settings.model_copy(update={"metrics_token": "scrape-token"})
    async with _client_for(scoped) as http:
        response = await http.get("/metrics", headers={"X-Metrics-Token": "wrong"})
        assert response.status_code == 401


async def test_metrics_is_not_exposed_in_production_without_a_token(
    test_settings: Settings,
) -> None:
    """Fail closed: an unprotected scrape endpoint is not shipped to production."""
    production = test_settings.model_copy(update={"app_env": "production"})
    async with _client_for(production) as http:
        assert (await http.get("/metrics")).status_code == 404


async def test_metrics_stays_open_in_development(test_settings: Settings) -> None:
    """Local scraping keeps working with no token configured."""
    async with _client_for(test_settings) as http:
        assert (await http.get("/metrics")).status_code == 200


def _boot_settings(base: Settings, **overrides: Any) -> Settings:
    """Construct fresh Settings, because `model_copy` skips validators.

    Startup guardrails are validation-time rules, so these probes have to build a real
    `Settings` rather than copy the fixture's.
    """
    values = {
        "database_url": "sqlite+aiosqlite:///:memory:",
        "redis_url": base.redis_url,
        "jwt_private_key_path": base.jwt_private_key_path,
        "jwt_public_key_path": base.jwt_public_key_path,
    }
    values.update(overrides)
    return Settings(**values)


def test_production_refuses_the_in_process_sandbox(test_settings: Settings) -> None:
    """`mock` execs LLM-generated code in this process; booting it in production is a
    misconfiguration, not a supported mode (audit C2/M1)."""
    with pytest.raises(ValidationError, match="SANDBOX_BACKEND=mock"):
        _boot_settings(test_settings, app_env="production", sandbox_backend="mock")


def test_production_boots_with_the_docker_sandbox(test_settings: Settings) -> None:
    settings = _boot_settings(
        test_settings, app_env="production", sandbox_backend="docker"
    )
    assert settings.sandbox_backend == "docker"


def test_development_also_refuses_the_in_process_sandbox(test_settings: Settings) -> None:
    """Mock sandbox is completely deprecated; real Docker is strictly required in all environments."""
    with pytest.raises(ValidationError, match="SANDBOX_BACKEND=mock"):
        _boot_settings(test_settings, app_env="development", sandbox_backend="mock")


async def test_docs_and_spec_are_not_served_in_production(test_settings: Settings) -> None:
    production = test_settings.model_copy(update={"app_env": "production"})
    async with _client_for(production) as http:
        assert (await http.get("/api/v1/docs")).status_code == 404
        assert (await http.get("/api/v1/openapi.json")).status_code == 404


async def test_docs_and_spec_are_served_in_development(test_settings: Settings) -> None:
    """`API.md §7` — the versioned spec stays available locally."""
    async with _client_for(test_settings) as http:
        assert (await http.get("/api/v1/docs")).status_code == 200
        spec = await http.get("/api/v1/openapi.json")
        assert spec.status_code == 200
        assert spec.json()["info"]["title"] == "APIWeaver Platform API"


async def test_lifespan_does_not_run_migrations_on_startup(test_settings: Settings, monkeypatch) -> None:
    """Lifespan must never execute alembic upgrade on startup, preventing multi-pod race conditions."""
    from unittest.mock import AsyncMock, MagicMock

    from alembic import command
    from app.main import lifespan

    executed = []

    def _mock_upgrade(cfg, rev):
        executed.append((cfg, rev))

    monkeypatch.setattr(command, "upgrade", _mock_upgrade)
    monkeypatch.setattr("redis.asyncio.from_url", lambda *args, **kwargs: AsyncMock())
    monkeypatch.setattr("app.main.dispose_engine", AsyncMock())
    monkeypatch.setattr("app.main.instrument_app", MagicMock())

    app = create_app(test_settings)
    async with lifespan(app):
        pass

    assert len(executed) == 0, "Alembic upgrade must not be executed during application lifespan"


def test_migration_runner_script(monkeypatch) -> None:
    """Standalone scripts/migrate.py executes alembic upgrade head with proper configuration."""
    import importlib.util

    from alembic import command

    executed = []

    def _mock_upgrade(cfg, rev):
        executed.append((cfg, rev))

    monkeypatch.setattr(command, "upgrade", _mock_upgrade)

    script_path = Path(__file__).resolve().parents[2] / "scripts" / "migrate.py"
    spec = importlib.util.spec_from_file_location("migrate", script_path)
    assert spec is not None and spec.loader is not None
    migrate_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migrate_module)

    migrate_module.run_migrations("head")
    assert len(executed) == 1
    assert executed[0][1] == "head"


async def test_llm_health_returns_config(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/llm")
    assert response.status_code == 200
    data = response.json()
    assert "provider" in data
    assert "model" in data
    assert "is_configured" in data


async def test_llm_test_endpoint_requires_auth(client: AsyncClient) -> None:
    response = await client.post("/api/v1/health/llm/test")
    assert response.status_code == 401



