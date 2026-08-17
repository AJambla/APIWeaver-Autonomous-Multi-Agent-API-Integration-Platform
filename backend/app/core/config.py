"""Application settings.

Every field maps to a key documented in `Deployment.md §9` / `.env.example`. Credentials
have no default value — a missing required secret fails at boot rather than silently
falling back to something insecure (`Security.md §7`).
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["development", "staging", "production"]


class Settings(BaseSettings):
    """Typed view of the process environment."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        # A typo'd env var is a misconfiguration, not something to ignore.
        extra="ignore",
    )

    # --- App -------------------------------------------------------------------
    app_env: AppEnv = "development"
    app_debug: bool = False
    log_level: str = "INFO"
    cors_allowed_origins: str = "http://localhost:3000"

    # --- Database (Deployment.md §9, required) ---------------------------------
    database_url: str

    # --- Redis (required) ------------------------------------------------------
    redis_url: str

    # --- Qdrant (required by §9; unused until Phase 2) ------------------------
    qdrant_url: str = "http://localhost:6333"

    # --- S3 / MinIO (required by §9; unused until Phase 2) --------------------
    s3_bucket_uploads: str = "apiweaver-uploads"
    s3_bucket_artifacts: str = "apiweaver-artifacts"
    s3_endpoint_url: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None

    # --- Vault (required by §9; client lands in Phase 2) ----------------------
    vault_addr: str = "http://localhost:8200"
    vault_token: str | None = None

    # --- LLM providers (conditional) ------------------------------------------
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    # --- JWT (Security.md §4) -------------------------------------------------
    # Paths, never key material: keys are files mounted by the Vault Agent Injector
    # in production (Deployment.md §9).
    jwt_private_key_path: Path
    jwt_public_key_path: Path
    jwt_access_token_expire_minutes: int = 60
    jwt_refresh_token_expire_days: int = 7
    jwt_algorithm: Literal["RS256"] = "RS256"
    jwt_issuer: str = "apiweaver"

    # --- GitHub Export (Phase 4) -------------------------------------------------
    github_app_id: str | None = None
    github_app_private_key_path: Path | None = None
    github_app_client_id: str | None = None
    github_app_client_secret_vault_path: str | None = None
    github_oauth_redirect_uri: str | None = None
    github_webhook_secret: str | None = None

    # --- Sandbox quotas (required by §9; enforced in Phase 4) -----------------
    sandbox_max_cpu: str = "1"
    sandbox_max_memory: str = "1Gi"
    sandbox_timeout_seconds: int = 300

    # --- Observability (recommended) ------------------------------------------
    langsmith_api_key: str | None = None
    otel_exporter_otlp_endpoint: str | None = None

    # --- Uploads (Security.md §10) --------------------------------------------
    max_upload_bytes: int = Field(default=50 * 1024 * 1024, description="50MB default")

    @field_validator("database_url")
    @classmethod
    def _require_async_driver(cls, value: str) -> str:
        """Reject a sync driver early — the whole data layer is async."""
        if not value.startswith(("postgresql+asyncpg://", "sqlite+aiosqlite://")):
            raise ValueError(
                "DATABASE_URL must use an async driver "
                "(postgresql+asyncpg:// or sqlite+aiosqlite:// for tests)"
            )
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton.

    Cached so the env is read once and key paths are resolved once. Tests clear the
    cache via `get_settings.cache_clear()`.
    """
    return Settings()  # type: ignore[call-arg]  # values come from the environment
