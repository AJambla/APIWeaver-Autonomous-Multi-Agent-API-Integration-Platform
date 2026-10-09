"""OpenTelemetry instrumentation for APIWeaver.

Wires OTel tracing into the FastAPI app, SQLAlchemy engine, and Redis client per
`Architecture.md §13` and `Deployment.md §9`.

Configuration is driven by settings and environment variables:
- `OTEL_EXPORTER_OTLP_ENDPOINT` — collector endpoint (required in production)
- `OTEL_SERVICE_NAME` — defaults to `apiweaver-api`
- `OTEL_SERVICE_VERSION` — defaults to the app version
- `LANGSMITH_API_KEY` — enables LangSmith trace correlation
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def is_telemetry_enabled() -> bool:
    """Return whether OpenTelemetry export is configured."""
    settings = get_settings()
    return bool(settings.otel_exporter_otlp_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))


def _build_resource() -> Any:
    """Build OpenTelemetry SDK resource descriptor."""
    from opentelemetry.sdk.resources import Resource

    settings = get_settings()
    return Resource.create(
        {
            "service.name": os.getenv("OTEL_SERVICE_NAME", "apiweaver-api"),
            "service.version": os.getenv("OTEL_SERVICE_VERSION", "1.0.0"),
            "deployment.environment": settings.app_env,
        }
    )


def _build_tracer_provider() -> Any:
    """Construct and register the TracerProvider with OTLP exporter if endpoint is configured."""
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    settings = get_settings()
    endpoint = settings.otel_exporter_otlp_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    resource = _build_resource()
    provider = TracerProvider(resource=resource)

    if endpoint:
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    return provider


def get_tracer(name: str = "apiweaver") -> Any:
    """Get a named OpenTelemetry tracer."""
    from opentelemetry import trace

    return trace.get_tracer(name)


@contextlib.contextmanager
def trace_span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    """Context manager for tracing arbitrary units of work."""
    from opentelemetry import trace

    tracer = trace.get_tracer("apiweaver")
    with tracer.start_as_current_span(name) as span:
        if attributes:
            for k, v in attributes.items():
                span.set_attribute(k, v)
        yield span


def instrument_app(app: Any, engine: Any) -> None:
    """Instrument FastAPI application, SQLAlchemy database engine, and Redis client."""
    if not is_telemetry_enabled():
        return

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.redis import RedisInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        _build_tracer_provider()
        FastAPIInstrumentor.instrument_app(app)

        sync_engine = getattr(engine, "sync_engine", engine)
        SQLAlchemyInstrumentor().instrument(engine=sync_engine)

        RedisInstrumentor().instrument()
        _setup_langsmith_correlation()
        logger.info("opentelemetry_instrumentation_initialized")
    except (ImportError, ModuleNotFoundError) as err:
        logger.debug("opentelemetry_packages_missing", error=str(err))
    except Exception as exc:
        logger.warning("opentelemetry_instrumentation_failed", error=str(exc))


def _setup_langsmith_correlation() -> None:
    """Set up LangSmith trace correlation processor if API key is present."""
    langsmith_key = os.getenv("LANGSMITH_API_KEY")
    if not langsmith_key:
        return

    try:
        from langsmith import Client as LangSmithClient
        from opentelemetry import trace
        from opentelemetry.sdk.trace import SpanProcessor

        client = LangSmithClient(api_key=langsmith_key)

        class LangSmithSpanProcessor(SpanProcessor):
            """Export completed spans to LangSmith for multi-agent correlation."""

            def __init__(self, langsmith_client: Any) -> None:
                self.client = langsmith_client

            def on_start(self, span: Any, parent_context: Any = None) -> None:
                pass

            def on_end(self, span: Any) -> None:
                try:
                    trace_id = format(span.get_span_context().trace_id, "032x")
                    span_status = "completed" if span.status.status_code == trace.StatusCode.UNSET else "error"
                    self.client.create_run(
                        name=span.name,
                        run_id=trace_id,
                        trace_id=trace_id,
                        parent_run_id=None,
                        start_time=span.start_time,
                        end_time=span.end_time,
                        status=span_status,
                        error=span.status.description or None,
                    )
                except Exception as err:
                    logger.debug("langsmith_span_export_failed", error=str(err))

            def shutdown(self) -> None:
                pass

            def force_flush(self, timeout_millis: int = 30000) -> bool:
                return True

        provider = trace.get_tracer_provider()
        if hasattr(provider, "add_span_processor"):
            provider.add_span_processor(LangSmithSpanProcessor(client))
            logger.info("langsmith_telemetry_correlation_enabled")
    except (ImportError, ModuleNotFoundError) as err:
        logger.debug("langsmith_client_missing", error=str(err))
    except Exception as exc:
        logger.warning("langsmith_correlation_failed", error=str(exc))
