#!/usr/bin/env python3
"""Database migration runner for APIWeaver.

Executes `alembic upgrade head` as a one-time init container, Kubernetes Job,
or deployment hook, preventing multi-pod race conditions on application startup.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("apiweaver.migrations")


def run_migrations(revision: str = "head") -> None:
    """Run database migrations to the target revision."""
    root_dir = Path(__file__).resolve().parent.parent
    backend_dir = root_dir / "backend"
    alembic_ini = backend_dir / "alembic.ini"

    if not alembic_ini.exists():
        logger.error(f"alembic.ini not found at {alembic_ini}")
        sys.exit(1)

    logger.info(f"Loading Alembic config from {alembic_ini}")
    alembic_cfg = Config(str(alembic_ini))
    alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))

    try:
        # Import settings to log target database host safely
        sys.path.insert(0, str(backend_dir))
        from app.core.config import get_settings

        settings = get_settings()
        # Ensure database url is set on config
        alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)

        logger.info(f"Applying Alembic migration to target: '{revision}'...")
        command.upgrade(alembic_cfg, revision)
        logger.info("Database migrations applied successfully.")
    except Exception as exc:
        logger.error(f"Database migration failed: {exc}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "head"
    run_migrations(target)
