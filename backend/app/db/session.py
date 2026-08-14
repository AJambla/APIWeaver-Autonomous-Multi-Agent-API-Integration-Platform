"""Async engine and session factory.

`Architecture.md §9` puts PgBouncer in transaction-pooling mode in front of Postgres, so
the application pool is modest and prepared-statement caching is disabled — asyncpg's
per-connection prepared statements do not survive a transaction-pooled connection being
handed to a different backend.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _engine_kwargs(settings: Settings) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "echo": False,
        "pool_pre_ping": True,
        "future": True,
    }
    if settings.database_url.startswith("postgresql+asyncpg://"):
        kwargs.update(
            pool_size=10,
            max_overflow=5,
            pool_recycle=1800,
            # Required behind PgBouncer transaction pooling (Architecture.md §9).
            connect_args={"statement_cache_size": 0},
        )
    return kwargs


def get_engine(settings: Settings | None = None) -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = settings or get_settings()
        _engine = create_async_engine(settings.database_url, **_engine_kwargs(settings))
    return _engine


def get_sessionmaker(settings: Settings | None = None) -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(settings),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session with request-scoped transaction handling.

    Commits on success, rolls back on any exception. Routes never manage the transaction
    boundary themselves, so a handler that raises mid-write cannot leave a partial commit.
    """
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Tear down the pool on shutdown."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
