"""Unit tests for LLM provider resilience: retries, backoff, circuit breaker."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import DependencyUnavailableError
from app.workflows import llm as llm_module
from app.workflows.llm import LLMClient


@pytest.fixture(autouse=True)
def _reset_circuits():
    llm_module._CIRCUITS.clear()
    yield
    llm_module._CIRCUITS.clear()


def _make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "app_env": "development",
        "database_url": "sqlite+aiosqlite:///:memory:",
        "redis_url": "redis://localhost:6379/0",
        "jwt_private_key_path": "test-jwt-key.pem",
        "jwt_public_key_path": "test-jwt-key.pub",
        "openai_api_key": "sk-test",
    }
    base.update(overrides)
    return Settings(**base)


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        *,
        headers: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self._headers = headers or {}
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
            response = httpx.Response(
                self.status_code, request=request, headers=self._headers
            )
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=request, response=response
            )

    def json(self) -> dict[str, Any]:
        return self._payload


def _install_fake_httpx(monkeypatch: pytest.MonkeyPatch, responses: list[Any]) -> dict:
    calls = {"count": 0}

    class _FakeAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _FakeAsyncClient:
            return self

        async def __aexit__(self, *exc_info: Any) -> bool:
            return False

        async def post(self, url: str, json: Any = None, headers: Any = None) -> Any:
            calls["count"] += 1
            item = responses.pop(0)
            if isinstance(item, Exception):
                raise item
            item.raise_for_status()
            return item

    monkeypatch.setattr(llm_module.httpx, "AsyncClient", _FakeAsyncClient)
    return calls


def _capture_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(llm_module, "asyncio", SimpleNamespace(sleep=fake_sleep))
    return sleeps


def _chat_ok(content: str = '{"ok": true}') -> FakeResponse:
    return FakeResponse(
        200,
        payload={
            "choices": [{"message": {"content": content}}],
            "usage": {"total_tokens": 42},
        },
    )


async def test_transient_500_retried_then_succeeds(monkeypatch):
    responses = [FakeResponse(500), _chat_ok()]
    calls = _install_fake_httpx(monkeypatch, responses)
    sleeps = _capture_sleep(monkeypatch)
    client = LLMClient(_make_settings(llm_max_retries=2))

    parsed, tokens = await client.generate_json(
        system_prompt="s", user_prompt="u"
    )

    assert parsed == {"ok": True}
    assert tokens == 42
    assert calls["count"] == 2
    assert sleeps == [0.5]


async def test_retry_after_header_honored(monkeypatch):
    responses = [FakeResponse(429, headers={"Retry-After": "3"}), _chat_ok()]
    calls = _install_fake_httpx(monkeypatch, responses)
    sleeps = _capture_sleep(monkeypatch)
    client = LLMClient(_make_settings(llm_max_retries=2))

    await client.generate_json(system_prompt="s", user_prompt="u")

    assert calls["count"] == 2
    assert sleeps == [3.0]


async def test_retry_after_capped_at_maximum(monkeypatch):
    responses = [FakeResponse(429, headers={"Retry-After": "300"}), _chat_ok()]
    _install_fake_httpx(monkeypatch, responses)
    sleeps = _capture_sleep(monkeypatch)
    client = LLMClient(_make_settings(llm_max_retries=2))

    await client.generate_json(system_prompt="s", user_prompt="u")

    assert sleeps == [10.0]


async def test_exhaustion_raises_dependency_unavailable(monkeypatch):
    responses = [FakeResponse(500), FakeResponse(503)]
    calls = _install_fake_httpx(monkeypatch, responses)
    sleeps = _capture_sleep(monkeypatch)
    client = LLMClient(_make_settings(llm_max_retries=1))

    with pytest.raises(DependencyUnavailableError, match="after 2 attempts"):
        await client.generate_json(system_prompt="s", user_prompt="u")

    assert calls["count"] == 2
    assert sleeps == [0.5]


async def test_permanent_401_raises_immediately_without_counting(monkeypatch):
    responses = [FakeResponse(401), _chat_ok()]
    calls = _install_fake_httpx(monkeypatch, responses)
    sleeps = _capture_sleep(monkeypatch)
    client = LLMClient(_make_settings(llm_max_retries=2))

    with pytest.raises(httpx.HTTPStatusError):
        await client.generate_json(system_prompt="s", user_prompt="u")

    assert calls["count"] == 1
    assert sleeps == []
    assert llm_module._CIRCUITS["openai"].failures == 0


async def test_transport_error_retried(monkeypatch):
    responses = [httpx.ConnectError("boom"), _chat_ok()]
    calls = _install_fake_httpx(monkeypatch, responses)
    sleeps = _capture_sleep(monkeypatch)
    client = LLMClient(_make_settings(llm_max_retries=2))

    parsed, _ = await client.generate_json(system_prompt="s", user_prompt="u")

    assert parsed == {"ok": True}
    assert calls["count"] == 2
    assert sleeps == [0.5]


async def test_circuit_opens_after_threshold_failures(monkeypatch):
    calls = _install_fake_httpx(monkeypatch, [FakeResponse(500) for _ in range(3)])
    _capture_sleep(monkeypatch)
    client = LLMClient(
        _make_settings(
            llm_max_retries=0,
            llm_circuit_failure_threshold=3,
            llm_circuit_cooldown_seconds=30.0,
        )
    )

    for _ in range(2):
        with pytest.raises(DependencyUnavailableError, match="unavailable after"):
            await client.generate_json(system_prompt="s", user_prompt="u")

    with pytest.raises(DependencyUnavailableError, match="circuit breaker is open"):
        await client.generate_json(system_prompt="s", user_prompt="u")

    with pytest.raises(DependencyUnavailableError, match="circuit breaker is open"):
        await client.generate_json(system_prompt="s", user_prompt="u")

    assert calls["count"] == 3


async def test_success_resets_failure_count(monkeypatch):
    responses = [
        FakeResponse(500),
        _chat_ok(),
        FakeResponse(500),
    ]
    _install_fake_httpx(monkeypatch, responses)
    _capture_sleep(monkeypatch)
    client = LLMClient(
        _make_settings(
            llm_max_retries=0,
            llm_circuit_failure_threshold=2,
            llm_circuit_cooldown_seconds=30.0,
        )
    )

    with pytest.raises(DependencyUnavailableError, match="unavailable after"):
        await client.generate_json(system_prompt="s", user_prompt="u")

    await client.generate_json(system_prompt="s", user_prompt="u")

    with pytest.raises(DependencyUnavailableError, match="unavailable after"):
        await client.generate_json(system_prompt="s", user_prompt="u")

    assert llm_module._CIRCUITS["openai"].opened_at is None


async def test_embedding_retry_then_success(monkeypatch):
    responses = [
        FakeResponse(500),
        FakeResponse(200, payload={"data": [{"embedding": [0.1, 0.2]}]}),
    ]
    calls = _install_fake_httpx(monkeypatch, responses)
    sleeps = _capture_sleep(monkeypatch)
    client = LLMClient(_make_settings(llm_max_retries=2, embedding_dimensions=2))

    embedding = await client.generate_embedding("hello")

    assert embedding == [0.1, 0.2]
    assert calls["count"] == 2
    assert sleeps == [0.5]


async def test_anthropic_wired_through_resilience(monkeypatch):
    responses = [
        FakeResponse(500),
        FakeResponse(
            200,
            payload={
                "content": [{"text": '{"ok": true}'}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        ),
    ]
    calls = _install_fake_httpx(monkeypatch, responses)
    _capture_sleep(monkeypatch)
    client = LLMClient(
        _make_settings(openai_api_key=None, anthropic_api_key="sk-ant-test")
    )

    parsed, tokens = await client.generate_json(system_prompt="s", user_prompt="u")

    assert parsed == {"ok": True}
    assert tokens == 15
    assert calls["count"] == 2


async def test_openai_compatible_custom_base_url_and_model(monkeypatch):
    """Test custom OpenAI-compatible endpoint (Ollama, vLLM, Groq, LM Studio)."""
    captured_requests = []

    class _CaptureClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _CaptureClient:
            return self

        async def __aexit__(self, *exc_info: Any) -> bool:
            return False

        async def post(self, url: str, json: Any = None, headers: Any = None) -> Any:
            captured_requests.append({"url": url, "json": json, "headers": headers})
            return FakeResponse(
                200,
                payload={
                    "choices": [{"message": {"content": "```json\n{\"generated\": \"local_success\"}\n```"}}],
                    "usage": {"total_tokens": 42},
                },
            )

    monkeypatch.setattr(llm_module.httpx, "AsyncClient", _CaptureClient)

    client = LLMClient(
        _make_settings(
            openai_api_key=None,
            openai_api_base_url="http://localhost:11434/v1",
            llm_model="qwen2.5-coder:7b",
        )
    )

    parsed, tokens = await client.generate_json(system_prompt="sys", user_prompt="usr")

    assert parsed == {"generated": "local_success"}
    assert tokens == 42
    assert len(captured_requests) == 1
    assert captured_requests[0]["url"] == "http://localhost:11434/v1/chat/completions"
    assert captured_requests[0]["json"]["model"] == "qwen2.5-coder:7b"
    assert captured_requests[0]["headers"]["Authorization"] == "Bearer none"


async def test_openai_compatible_custom_embedding_endpoint(monkeypatch):
    """Test custom embedding endpoint (Ollama, vLLM, LocalAI)."""
    captured_requests = []

    class _CaptureClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _CaptureClient:
            return self

        async def __aexit__(self, *exc_info: Any) -> bool:
            return False

        async def post(self, url: str, json: Any = None, headers: Any = None) -> Any:
            captured_requests.append({"url": url, "json": json})
            return FakeResponse(
                200,
                payload={"data": [{"embedding": [0.5, 0.6, 0.7]}]},
            )

    monkeypatch.setattr(llm_module.httpx, "AsyncClient", _CaptureClient)

    client = LLMClient(
        _make_settings(
            openai_api_key=None,
            embedding_base_url="http://localhost:11434/v1",
            embedding_model="nomic-embed-text",
            embedding_dimensions=3,
        )
    )

    vector = await client.generate_embedding("hello local embedding")

    assert vector == [0.5, 0.6, 0.7]
    assert len(captured_requests) == 1
    assert captured_requests[0]["url"] == "http://localhost:11434/v1/embeddings"
    assert captured_requests[0]["json"]["model"] == "nomic-embed-text"


async def test_gemini_via_openai_compatible_endpoint(monkeypatch):
    """Test Google Gemini using its official OpenAI-compatible endpoint."""
    captured_requests = []

    class _CaptureClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _CaptureClient:
            return self

        async def __aexit__(self, *exc_info: Any) -> bool:
            return False

        async def post(self, url: str, json: Any = None, headers: Any = None) -> Any:
            captured_requests.append({"url": url, "json": json, "headers": headers})
            return FakeResponse(
                200,
                payload={
                    "choices": [{"message": {"content": '{"gemini": "openai_compatible"}'}}],
                    "usage": {"total_tokens": 30},
                },
            )

    monkeypatch.setattr(llm_module.httpx, "AsyncClient", _CaptureClient)

    client = LLMClient(
        _make_settings(
            openai_api_key="AIzaSyTestKey",
            openai_api_base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            llm_model="gemini-2.0-flash",
        )
    )

    parsed, tokens = await client.generate_json(system_prompt="s", user_prompt="u")

    assert parsed == {"gemini": "openai_compatible"}
    assert tokens == 30
    assert len(captured_requests) == 1
    assert captured_requests[0]["url"] == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert captured_requests[0]["json"]["model"] == "gemini-2.0-flash"
    assert captured_requests[0]["headers"]["Authorization"] == "Bearer AIzaSyTestKey"


async def test_anthropic_custom_base_url(monkeypatch):
    """Test custom Anthropic API base URL configuration."""
    captured_requests = []

    class _CaptureClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _CaptureClient:
            return self

        async def __aexit__(self, *exc_info: Any) -> bool:
            return False

        async def post(self, url: str, json: Any = None, headers: Any = None) -> Any:
            captured_requests.append({"url": url, "json": json, "headers": headers})
            return FakeResponse(
                200,
                payload={
                    "content": [{"text": '{"anthropic_custom": true}'}],
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
            )

    monkeypatch.setattr(llm_module.httpx, "AsyncClient", _CaptureClient)

    client = LLMClient(
        _make_settings(
            openai_api_key=None,
            anthropic_api_key="sk-ant-test",
            anthropic_api_base_url="https://mock-anthropic.internal/v1",
        )
    )

    parsed, tokens = await client.generate_json(system_prompt="s", user_prompt="u")

    assert parsed == {"anthropic_custom": True}
    assert tokens == 15
    assert len(captured_requests) == 1
    assert captured_requests[0]["url"] == "https://mock-anthropic.internal/v1/messages"
    assert captured_requests[0]["headers"]["x-api-key"] == "sk-ant-test"


async def test_json_decode_error_retried_then_succeeds(monkeypatch):
    """Malformed/truncated JSON responses are treated as transient errors and retried."""
    attempts = 0

    class _FlakyJsonClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _FlakyJsonClient:
            return self

        async def __aexit__(self, *exc_info: Any) -> bool:
            return False

        async def post(self, url: str, json: Any = None, headers: Any = None) -> Any:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                # Malformed JSON from provider
                return FakeResponse(
                    200,
                    payload={"choices": [{"message": {"content": "not valid json {{"}, "finish_reason": "stop"}]},
                )
            return FakeResponse(
                200,
                payload={"choices": [{"message": {"content": '{"recovered": true}'}, "finish_reason": "stop"}]},
            )

    monkeypatch.setattr(llm_module.httpx, "AsyncClient", _FlakyJsonClient)
    client = LLMClient(_make_settings(llm_max_retries=2, llm_retry_delay_seconds=0.01))
    parsed, _ = await client.generate_json(system_prompt="s", user_prompt="u")

    assert parsed == {"recovered": True}
    assert attempts == 2




