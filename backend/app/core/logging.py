"""Structured JSON logging with secret redaction.

`Deployment.md §11` requires structured JSON logs with `request_id`/`workflow_run_id`
correlation IDs. `Security.md §19` requires redaction on all log paths, tested with
canary-secret injection — redaction happens here, at emission time, so no caller can
forget it.
"""

from __future__ import annotations

import logging
import re
import sys
from contextvars import ContextVar
from typing import Any

import structlog

# Correlation IDs. Set by middleware (request_id) and by the orchestrator once workflows
# exist (workflow_run_id, Phase 3) — bound into every log line automatically.
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")
workflow_run_id_ctx: ContextVar[str] = ContextVar("workflow_run_id", default="")

REDACTED = "***REDACTED***"

# Keys whose values are never safe to log, matched case-insensitively against any
# substring of the key name.
_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "api_key",
    "apikey",
    "credential",
    "private_key",
    "session",
    "cookie",
    "vault",
)

# Value-level patterns, for secrets that leak inside an otherwise-innocuous message.
_SENSITIVE_VALUE_PATTERNS = (
    # Platform API keys (Security.md §5)
    re.compile(r"apw_(?:live|test)_[A-Za-z0-9]+"),
    # Authorization header values
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+"),
    # JWTs anywhere
    re.compile(r"\beyJ[A-Za-z0-9._\-]{10,}"),
    # PEM blocks
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
)

_MAX_REDACT_DEPTH = 6


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def _redact_value(value: Any, depth: int = 0) -> Any:
    """Recursively redact secrets from a log value.

    Depth-bounded: a pathological nested structure should degrade to a placeholder
    rather than blow the stack inside a logging call.
    """
    if depth > _MAX_REDACT_DEPTH:
        return "***TRUNCATED***"
    if isinstance(value, str):
        for pattern in _SENSITIVE_VALUE_PATTERNS:
            value = pattern.sub(REDACTED, value)
        return value
    if isinstance(value, dict):
        return {
            key: REDACTED if _is_sensitive_key(str(key)) else _redact_value(item, depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_redact_value(item, depth + 1) for item in value]
    return value


def redact_processor(
    _logger: Any, _method_name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    """structlog processor applying `Security.md §19` redaction to the whole event."""
    return {
        key: REDACTED if _is_sensitive_key(str(key)) else _redact_value(value)
        for key, value in event_dict.items()
    }


def correlation_processor(
    _logger: Any, _method_name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    """Attach correlation IDs so cross-service tracing works (Deployment.md §11)."""
    if request_id := request_id_ctx.get():
        event_dict.setdefault("request_id", request_id)
    if workflow_run_id := workflow_run_id_ctx.get():
        event_dict.setdefault("workflow_run_id", workflow_run_id)
    return event_dict


def configure_logging(*, level: str = "INFO", json_output: bool = True) -> None:
    """Install the logging pipeline. Idempotent — safe to call per app construction."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=numeric_level, force=True)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        correlation_processor,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        # Redaction runs last so it also covers rendered exception text.
        redact_processor,
    ]

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
