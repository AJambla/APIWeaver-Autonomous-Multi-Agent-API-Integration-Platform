"""OpenTelemetry instrumentation for APIWeaver.

Wires OTel tracing into the FastAPI app, SQLAlchemy engine, and Redis client per
`Architecture.md §13` and `Deployment.md §9`.

Configuration is driven by environment variables:
- `OTEL_EXPORTER_OTLP_ENDPOINT` — collector endpoint (required in production)
- `OTEL_SERVICE_NAME` — defaults to `apiweaver-api`
- `OTEL_SERVICE_VERSION` — defaults to the app version
- `LANGSMITH_API_KEY` — enables LangSmith trace correlation
"""

from __future__ import annotations

import os
from typing import Any

from app.core.config import get_settings


def _build_resource() -> Any:
    from opentelemetry.sdk.resources import Resource
    settings = get_settings()
    return Resource.create(
        {
            "service.name": os.getenv("OTEL_SERVICE_NAME", "apiweaver-api"),
            "service.version": os.getenv("OTEL_SERVICE_VERSION", "1.0.0"),
            "deployment.environment": settings.app_env,
            "app.request_id": "{{request_id}}",
        }
    )


def _build_tracer_provider() -> Any:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    resource = _build_resource()
    provider = TracerProvider(resource=resource)

    if endpoint:
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    return provider


def instrument_app(app: Any, engine: Any) -> None:
    settings = get_settings()
    if not settings.otel_exporter_otlp_endpoint:
        return

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        _build_tracer_provider()
        FastAPIInstrumentor.instrument_app(app)
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
        _setup_langsmith_correlation()
    except (ImportError, ModuleNotFoundError):
        pass



def _setup_langsmith_correlation() -> None:
    langsmith_key = os.getenv("LANGSMITH_API_KEY")
    if not langsmith_key:
        return

    try:
        from langsmith import Client as LangSmithClient

        client = LangSmithClient(api_key=langsmith_key)

        def langsmith_span_processor(span: Any) -> None:
            try:
                trace_id = format(span.get_span_context().trace_id, "032x")
                client.create_run(
                    name=span.name,
                    run_id=trace_id,
                    trace_id=trace_id,
                    parent_run_id=None,
                    start_time=span.start_time,
                    end_time=span.end_time,
                    status="completed"
                    if span.status.status_code == trace.StatusCode.UNSET
                    else "error",
                    error=span.status.description or None,
                )
            except Exception:  # noqa: BLE001 — non-critical correlation
                pass

        trace.get_tracer_provider().add_span_processor(langsmith_span_processor)
    except ImportError:
        pass
