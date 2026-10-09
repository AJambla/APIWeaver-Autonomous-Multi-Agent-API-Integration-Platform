"""Application settings.

Every field maps to a key documented in `Deployment.md §9` / `.env.example`. Credentials
have no default value — a missing required secret fails at boot rather than silently
falling back to something insecure (`Security.md §7`).
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.constants import DEFAULT_WORKFLOW_NODE_PROGRESS

AppEnv = Literal["development", "staging", "production"]

DEFAULT_MODEL_PRICING_PER_TOKEN: dict[str, float] = {
    "gpt-4o-mini": 0.0000003,
    "gpt-4o": 0.000005,
    "gpt-4-turbo": 0.00001,
    "claude-3-5-sonnet": 0.000003,
    "claude-3-5-sonnet-20241022": 0.000003,
    "claude-3-haiku": 0.00000025,
    "gemini-2.0-flash": 0.0000001,
    "gemini-1.5-pro": 0.00000125,
    "gemini-1.5-flash": 0.000000075,
    "deepseek-chat": 0.00000014,
}


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
    db_pool_size: int = 10
    db_max_overflow: int = 5
    db_pool_timeout: float = 30.0
    db_pool_recycle: int = 1800
    db_echo: bool = False

    # --- Redis (required) ------------------------------------------------------
    redis_url: str
    # Bounded so a blackholed Redis fails fast: the rate limiter fails open and the JWT
    # denylist check fails closed (503) instead of every request hanging on a dead socket.
    redis_connect_timeout_seconds: float = 1.0
    redis_socket_timeout_seconds: float = 2.0
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    redis_stream_workflow_maxlen: int = 1000
    redis_stream_project_maxlen: int = 2000
    redis_stream_workflow_ttl_seconds: int = 86400
    redis_stream_project_ttl_seconds: int = 604800  # 7 days

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
    vault_mount_path: str = "secret"
    qdrant_timeout_seconds: float = 10.0
    github_timeout_seconds: float = 30.0

    # --- Rate Limiting --------------------------------------------------------
    rate_limit_free_rpm: int = 120
    rate_limit_pro_rpm: int = 600
    rate_limit_enterprise_rpm: int = 3000

    # --- LLM providers (conditional) ------------------------------------------
    openai_api_key: str | None = None
    openai_api_base_url: str = "https://api.openai.com/v1"
    anthropic_api_key: str | None = None
    anthropic_api_base_url: str = "https://api.anthropic.com/v1"
    llm_model: str = "gpt-4o-mini"
    anthropic_model: str = "claude-3-5-sonnet-20241022"
    embedding_model: str = "text-embedding-3-small"
    llm_max_retry_delay_seconds: float = 8.0
    llm_max_retry_after_seconds: float = 10.0
    llm_temperature: float = 0.1
    llm_request_timeout: float = 60.0
    llm_max_tokens: int = 4096
    embedding_base_url: str | None = None
    # Chunks of a single document that get embedded and indexed. Without a ceiling, one
    # 50MB upload is ~100k provider calls (audit M8); the remainder is skipped loudly.
    max_embedding_chunks: int = 2000

    # --- Token budget & model pricing (audit §2.4, item 15) -------------------
    default_token_budget: int = 1_000_000
    default_token_price: float = 0.000003
    model_pricing_per_token: dict[str, float] = Field(
        default_factory=lambda: dict(DEFAULT_MODEL_PRICING_PER_TOKEN)
    )

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
    github_app_slug: str = "apiweaver"
    github_app_private_key_path: Path | None = None
    github_app_client_id: str | None = None
    github_app_client_secret_vault_path: str | None = None
    github_oauth_redirect_uri: str | None = None
    github_webhook_secret: str | None = None
    github_api_base_url: str = "https://api.github.com"
    github_oauth_authorize_url: str = "https://github.com/login/oauth/authorize"
    github_oauth_token_url: str = "https://github.com/login/oauth/access_token"

    # --- Sandbox quotas (required by §9; enforced in Phase 4) -----------------
    # Production-level sandbox isolates generated code in a 4GB Docker container.
    sandbox_backend: Literal["docker", "mock"] = "docker"
    # Explicit Docker daemon URL (e.g. "unix:///var/run/docker.sock" or "tcp://docker-dind:2375").
    # If None, docker.from_env() resolves from DOCKER_HOST or local default.
    docker_host: str | None = None
    # Built from infra/docker/Dockerfile.sandbox-python (Python + httpx + pydantic, which
    # generated clients import). Production should pin the CI-published image by digest,
    # e.g. ghcr.io/<owner>/<repo>/sandbox-python@sha256:...
    sandbox_image: str = "apiweaver/sandbox-python:latest"
    sandbox_node_image: str = (
        "node:22-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402"
    )
    sandbox_max_cpu: str = "1"
    sandbox_max_memory: str = "1Gi"
    sandbox_timeout_seconds: int = 300
    sandbox_pids_limit: int = 64
    # Deprecated and ignored: it used to give *hermetic* runs network access, skipping the
    # live-mode target vetting. Only `environment="live"` runs get a network now. Kept so a
    # deployment that still sets it gets a startup warning instead of silent behaviour change.
    sandbox_network_enabled: bool = False
    # `environment="live"` tests call the real target API and therefore need network.
    # Off unless the deployment opts in; targets are still vetted against private,
    # loopback and metadata addresses unless `sandbox_allow_private_targets` is set.
    sandbox_live_network_enabled: bool = False
    sandbox_allow_private_targets: bool = False
    # Docker network for networked sandboxes (None = the daemon's default bridge), and
    # an HTTP(S) proxy to force their egress through (recommended: an allow-listing proxy).
    sandbox_network: str | None = None
    sandbox_egress_proxy: str | None = None
    sandbox_log_tail_lines: int = 2000
    sandbox_log_max_bytes: int = 256 * 1024
    sandbox_read_only_rootfs: bool = True

    # --- Observability (recommended) ------------------------------------------
    langsmith_api_key: str | None = None
    otel_exporter_otlp_endpoint: str | None = None
    # Shared secret the scraper sends as X-Metrics-Token. Production will not expose
    # /metrics at all without it (audit M4).
    metrics_token: str | None = None

    # --- Uploads (Security.md §10) --------------------------------------------
    max_upload_bytes: int = Field(default=50 * 1024 * 1024, description="50MB default")
    # Spec import by URL is fetched server-side; private/loopback targets are refused
    # unless this is set (trusted local development only).
    spec_fetch_allow_private_targets: bool = False

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
    # Where workflow runs execute: "celery" (the agent worker) or "inline" (FastAPI
    # BackgroundTasks; development only). Production always uses the worker.
    workflow_dispatch: Literal["inline", "celery"] = "inline"
    # Hard/soft limits for one whole workflow run inside the worker. Stage tasks keep the
    # shorter Celery defaults; a full pipeline (LLM codegen + sandbox tests + repairs)
    # routinely needs more than five minutes.
    workflow_task_time_limit_seconds: int = 3600
    # Workflow progress percentage mapping by node name
    workflow_node_progress_map: dict[str, int] = Field(
        default_factory=lambda: dict(DEFAULT_WORKFLOW_NODE_PROGRESS)
    )

    @field_validator("workflow_node_progress_map", mode="before")
    @classmethod
    def _parse_workflow_node_progress(cls, value: Any) -> dict[str, int]:
        """Parse JSON string if set via environment variable, and merge with defaults."""
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except Exception as e:
                raise ValueError(f"Invalid JSON string for workflow_node_progress_map: {e}") from e
            if not isinstance(parsed, dict):
                raise ValueError("workflow_node_progress_map JSON must be an object/dict")
            value = parsed
        if isinstance(value, dict):
            merged = dict(DEFAULT_WORKFLOW_NODE_PROGRESS)
            for k, v in value.items():
                merged[str(k)] = int(v)
            return merged
        return dict(DEFAULT_WORKFLOW_NODE_PROGRESS)

    @field_validator("model_pricing_per_token", mode="before")
    @classmethod
    def _parse_model_pricing(cls, value: Any) -> dict[str, float]:
        """Parse JSON string if set via environment variable, and merge with defaults."""
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except Exception as e:
                raise ValueError(f"Invalid JSON string for model_pricing_per_token: {e}") from e
            if not isinstance(parsed, dict):
                raise ValueError("model_pricing_per_token JSON must be an object/dict")
            value = parsed
        if isinstance(value, dict):
            merged = dict(DEFAULT_MODEL_PRICING_PER_TOKEN)
            for k, v in value.items():
                merged[str(k)] = float(v)
            return merged
        return value

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
        it is a test-only opt-in; a production or staging deployment that asks for it is a
        misconfiguration, not a supported mode.
        """
        if self.sandbox_backend != "docker":
            raise ValueError(
                f"SANDBOX_BACKEND={self.sandbox_backend} cannot be used in "
                f"{self.app_env} mode. A real Docker daemon is strictly required."
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


def validate_startup_environment(settings: Settings) -> None:
    """Validate critical environment requirements at application startup.

    Enforces fail-loud pre-flight checks before the application begins accepting requests:
    - DATABASE_URL is set and non-empty.
    - REDIS_URL is set and non-empty.
    - JWT private and public key files exist on disk and are readable.
    - In production mode: strictly requires at least one active LLM provider key
      (OPENAI_API_KEY or ANTHROPIC_API_KEY).
    """
    if not settings.database_url or not settings.database_url.strip():
        raise ValueError("DATABASE_URL must be set and non-empty.")

    if not settings.redis_url or not settings.redis_url.strip():
        raise ValueError("REDIS_URL must be set and non-empty.")

    if settings.sandbox_network_enabled:
        from app.core.logging import get_logger

        get_logger(__name__).warning(
            "deprecated_setting_ignored",
            setting="SANDBOX_NETWORK_ENABLED",
            detail=(
                "Hermetic sandbox runs never get network access. Use "
                "SANDBOX_LIVE_NETWORK_ENABLED with environment='live' to test a real API."
            ),
        )

    def _resolve_path(path: Path) -> Path:
        if path.is_file():
            return path
        backend_dir = Path(__file__).resolve().parents[2]
        if (backend_dir / path).is_file():
            return backend_dir / path
        repo_root = Path(__file__).resolve().parents[3]
        if (repo_root / path).is_file():
            return repo_root / path
        return path

    private_key = _resolve_path(settings.jwt_private_key_path)
    if not private_key.is_file():
        raise FileNotFoundError(
            f"JWT private key not found at '{settings.jwt_private_key_path}'. "
            "Ensure keys are mounted from Vault or generated via scripts/gen_jwt_keys.sh."
        )

    public_key = _resolve_path(settings.jwt_public_key_path)
    if not public_key.is_file():
        raise FileNotFoundError(
            f"JWT public key not found at '{settings.jwt_public_key_path}'. "
            "Ensure keys are mounted from Vault or generated via scripts/gen_jwt_keys.sh."
        )

    if settings.is_production:
        has_openai = bool(settings.openai_api_key and settings.openai_api_key.strip())
        has_anthropic = bool(settings.anthropic_api_key and settings.anthropic_api_key.strip())
        if not (has_openai or has_anthropic):
            raise ValueError(
                "Production mode strictly requires at least one configured LLM provider key "
                "(OPENAI_API_KEY or ANTHROPIC_API_KEY)."
            )
