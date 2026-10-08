"""Tests for OpenTelemetry and LangSmith tracing setup."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.core.telemetry import (
    _build_resource,
    _build_tracer_provider,
    _setup_langsmith_correlation,
    get_tracer,
    instrument_app,
    is_telemetry_enabled,
    trace_span,
)


def test_is_telemetry_enabled_when_unset(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    with patch("app.core.telemetry.get_settings") as mock_get_settings:
        mock_get_settings.return_value = Settings(
            database_url="postgresql+asyncpg://user:pass@localhost:5432/db",
            redis_url="redis://localhost:6379/0",
            otel_exporter_otlp_endpoint=None,
        )
        assert not is_telemetry_enabled()


def test_is_telemetry_enabled_when_set(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    assert is_telemetry_enabled()


def test_build_resource(monkeypatch):
    monkeypatch.setenv("OTEL_SERVICE_NAME", "custom-apiweaver")
    monkeypatch.setenv("OTEL_SERVICE_VERSION", "2.1.0")
    resource = _build_resource()
    attributes = resource.attributes
    assert attributes.get("service.name") == "custom-apiweaver"
    assert attributes.get("service.version") == "2.1.0"


def test_trace_span_context_manager():
    tracer = get_tracer("test_tracer")
    assert tracer is not None
    with trace_span("test_unit_span", attributes={"workflow_id": "test-123"}) as span:
        assert span is not None


def test_instrument_app_skips_when_disabled(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    with patch("app.core.telemetry.get_settings") as mock_get_settings:
        mock_get_settings.return_value = Settings(
            database_url="postgresql+asyncpg://user:pass@localhost:5432/db",
            redis_url="redis://localhost:6379/0",
            otel_exporter_otlp_endpoint=None,
        )
        with patch("opentelemetry.instrumentation.fastapi.FastAPIInstrumentor.instrument_app") as mock_fastapi:
            instrument_app(FastAPI(), MagicMock())
            assert not mock_fastapi.called


def test_instrument_app_initializes_when_enabled(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    with patch("opentelemetry.instrumentation.fastapi.FastAPIInstrumentor.instrument_app") as mock_fastapi, \
         patch("opentelemetry.instrumentation.sqlalchemy.SQLAlchemyInstrumentor.instrument") as mock_sql, \
         patch("opentelemetry.instrumentation.redis.RedisInstrumentor.instrument") as mock_redis, \
         patch("app.core.telemetry._build_tracer_provider"):

        mock_engine = MagicMock()
        mock_engine.sync_engine = MagicMock()
        instrument_app(FastAPI(), mock_engine)

        assert mock_fastapi.called
        assert mock_sql.called
        assert mock_redis.called


def test_langsmith_correlation_sets_span_processor(monkeypatch):
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_pt_test_key_123")

    with patch("langsmith.Client") as mock_langsmith_cls, \
         patch("opentelemetry.trace.get_tracer_provider") as mock_provider_func:

        mock_provider = MagicMock()
        mock_provider_func.return_value = mock_provider

        _setup_langsmith_correlation()

        assert mock_langsmith_cls.called
        assert mock_provider.add_span_processor.called

        # Test on_end processor
        processor = mock_provider.add_span_processor.call_args[0][0]
        mock_span = MagicMock()
        mock_span.name = "test_span"
        mock_span.get_span_context().trace_id = 12345
        mock_span.status.status_code = 0
        mock_span.start_time = 1000
        mock_span.end_time = 2000

        processor.on_end(mock_span)
        assert processor.client.create_run.called
