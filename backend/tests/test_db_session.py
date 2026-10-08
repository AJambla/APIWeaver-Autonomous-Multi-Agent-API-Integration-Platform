"""Unit tests for database session and connection pool configuration."""

from __future__ import annotations

from app.core.config import Settings
from app.db.session import _engine_kwargs


def _make_settings(**overrides) -> Settings:
    defaults = {
        "database_url": "postgresql+asyncpg://user:pass@localhost:5432/testdb",
        "redis_url": "redis://localhost:6379/0",
        "jwt_private_key_path": "./secrets/jwt_private.pem",
        "jwt_public_key_path": "./secrets/jwt_public.pem",
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_default_database_pool_settings():
    settings = _make_settings()
    kwargs = _engine_kwargs(settings)

    assert kwargs["echo"] is False
    assert kwargs["pool_pre_ping"] is True
    assert kwargs["future"] is True
    assert kwargs["pool_size"] == 10
    assert kwargs["max_overflow"] == 5
    assert kwargs["pool_timeout"] == 30.0
    assert kwargs["pool_recycle"] == 1800
    assert kwargs["connect_args"] == {"statement_cache_size": 0}


def test_custom_database_pool_settings():
    settings = _make_settings(
        db_pool_size=25,
        db_max_overflow=12,
        db_pool_timeout=60.0,
        db_pool_recycle=900,
        db_echo=True,
    )
    kwargs = _engine_kwargs(settings)

    assert kwargs["echo"] is True
    assert kwargs["pool_size"] == 25
    assert kwargs["max_overflow"] == 12
    assert kwargs["pool_timeout"] == 60.0
    assert kwargs["pool_recycle"] == 900


def test_sqlite_url_does_not_inject_queue_pool_kwargs():
    settings = _make_settings(database_url="sqlite+aiosqlite:///:memory:")
    kwargs = _engine_kwargs(settings)

    assert kwargs["echo"] is False
    assert kwargs["pool_pre_ping"] is True
    assert kwargs["future"] is True
    assert "pool_size" not in kwargs
    assert "max_overflow" not in kwargs
    assert "pool_timeout" not in kwargs
    assert "pool_recycle" not in kwargs
    assert "connect_args" not in kwargs
