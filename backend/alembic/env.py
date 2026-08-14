"""Alembic environment.

Reads the connection string from `Settings` rather than `alembic.ini` so there is one
source of truth and no credential in a checked-in file (`Security.md §7`).
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import Any

from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.core.config import get_settings

# Importing the package registers every model on Base.metadata. Without this,
# autogenerate would see an empty schema and emit drops for everything.
from app.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)


def include_object(
    obj: Any,
    name: str | None,
    type_: str,
    _reflected: bool,
    _compare_to: Any,
) -> bool:
    """Exclude natively-partitioned tables and their partitions from autogenerate.

    `agent_events` and `usage_metrics` are created by raw DDL in `0002` because
    SQLAlchemy cannot express `PARTITION BY RANGE`. Left to its own devices, autogenerate
    would compare the model against the partitioned reality and emit a migration that
    "fixes" them into plain tables, silently destroying the partitioning on the next
    deploy. Their child partitions are likewise invisible to the model, so they are
    filtered by name prefix.
    """
    if type_ == "table":
        if obj.info.get("managed_by_migration"):
            return False
        if name and name.startswith(("agent_events_", "usage_metrics_")):
            return False
    return True


def _configure_common() -> dict[str, Any]:
    return {
        "target_metadata": target_metadata,
        "include_object": include_object,
        # Detect column type changes, not just adds/drops.
        "compare_type": True,
        "compare_server_default": True,
        # Emit constraint names using db/base.py's naming convention so downgrade()
        # can drop them by name.
        "render_as_batch": False,
    }


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of executing — used to review a migration before
    it runs in CI (Database.md §6)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_configure_common(),
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, **_configure_common())
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
