"""Application settings.

Every field maps to a key documented in `Deployment.md §9` / `.env.example`. Credentials
have no default value — a missing required secret fails at boot rather than silently
falling back to something insecure (`Security.md §7`).
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
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
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

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
    openai_api_base_url: str = "https://api.openai.com/v1"
    anthropic_api_key: str | None = None
    llm_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    embedding_base_url: str | None = None
    # Chunks of a single document that get embedded and indexed. Without a ceiling, one
    # 50MB upload is ~100k provider calls (audit M8); the remainder is skipped loudly.
    max_embedding_chunks: int = 2000

    # --- LLM resilience (transient failures + provider circuit breaker) -------
    llm_max_retries: int = 2
    llm_retry_backoff_seconds: float = 0.5
    llm_circuit_failure_threshold: int = 5
    llm_circuit_cooldown_seconds: float = 30.0

    # --- JWT (Security.md §4) -------------------------------------------------
    # Paths, never key material: keys are files mounted by the Vault Agent Injector
    # in production (Deployment.md §9).
    jwt_private_key_path: Path
    jwt_public_key_path: Path
    jwt_access_token_expire_minutes: int = 60
    jwt_refresh_token_expire_days: int = 7
    jwt_algorithm: Literal["RS256"] = "RS256"
    jwt_issuer: str = "apiweaver"

    # --- Per-account lockout (Security.md §1, audit M2) -----------------------
    # Counted in the `users` row, not the Redis limiter, because the Redis limiter
    # fails open and is keyed per IP; a distributed attack or an outage must not
    # turn into an unlocked front door.
    login_max_failed_attempts: int = 5
    login_lockout_minutes: int = 15

    # --- GitHub Export (Phase 4) -------------------------------------------------
    github_app_id: str | None = None
    github_app_private_key_path: Path | None = None
    github_app_client_id: str | None = None
    github_app_client_secret_vault_path: str | None = None
    github_oauth_redirect_uri: str | None = None
    github_webhook_secret: str | None = None

    # --- Sandbox quotas (required by §9; enforced in Phase 4) -----------------
    # "docker" isolates generated code in a quota-enforced container; "mock"
    # execs LLM-generated code inside the API process (test-only opt-in).
    sandbox_backend: Literal["mock", "docker"] = "docker"
    # Explicit Docker daemon URL (e.g. "unix:///var/run/docker.sock" or "tcp://docker-dind:2375").
    # If None, docker.from_env() resolves from DOCKER_HOST or local default.
    docker_host: str | None = None
    sandbox_image: str = "python:3.12-slim"
    sandbox_node_image: str = "node:22-alpine"
    sandbox_max_cpu: str = "1"
    sandbox_max_memory: str = "256Mi"
    sandbox_timeout_seconds: int = 300
    sandbox_pids_limit: int = 64
    sandbox_network_enabled: bool = False
    sandbox_read_only_rootfs: bool = True

    # --- Observability (recommended) ------------------------------------------
    langsmith_api_key: str | None = None
    otel_exporter_otlp_endpoint: str | None = None
    # Shared secret the scraper sends as X-Metrics-Token. Production will not expose
    # /metrics at all without it (audit M4).
    metrics_token: str | None = None

    # --- Uploads (Security.md §10) --------------------------------------------
    max_upload_bytes: int = Field(default=50 * 1024 * 1024, description="50MB default")

    # --- Proxy topology (audit L1) --------------------------------------------
    # How many reverse proxies sit between the internet and this process, each of which
    # appends the peer it saw to `X-Forwarded-For`. Both documented shapes are one hop:
    # the ALB in front of EKS (`Architecture.md §11`) and nginx's
    # `proxy_set_header X-Forwarded-For` (`frontend/nginx.conf`). Anything the client sent
    # first is to the LEFT of those appends, so `trusted_proxy_hops` is how far from the
    # right we may read. 0 means nothing in front is trusted: `X-Forwarded-For` is then
    # ignored and the transport peer is used even though it names a load balancer.
    trusted_proxy_hops: int = Field(default=1, ge=0, le=4)

    # --- Workflow execution (Task 7.5) ----------------------------------------
    # Enable parallel agent execution within a workflow run. Default off for
    # incremental rollout; turn on after smoke testing.
    enable_parallel_agents: bool = False
    # In production, require Celery workers for async workflows rather than
    # silently running on API process BackgroundTasks (fail-loud queueing).
    require_celery_worker: bool = False
    # Default workflow orchestration engine: "standard" (linear orchestrator)
    # or "langgraph" (state graph with cyclic repairs and conditional edges).
    default_workflow_engine: Literal["standard", "langgraph"] = "standard"

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

    @model_validator(mode="after")
    def _refuse_unsandboxed_production(self) -> Settings:
        """Fail boot rather than run generated code inside the API process (audit C2/M1).

        `sandbox_backend="mock"` imports and executes LLM-authored modules in-process, so
        it is a test-only opt-in; a production deployment that asks for it is a
        misconfiguration, not a supported mode.
        """
        if self.app_env == "production" and self.sandbox_backend == "mock":
            raise ValueError(
                "SANDBOX_BACKEND=mock runs LLM-generated code in this process and is "
                "test-only; production must use SANDBOX_BACKEND=docker."
            )
        return self

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
