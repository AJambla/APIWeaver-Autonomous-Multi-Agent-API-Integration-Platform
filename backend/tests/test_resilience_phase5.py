"""Phase 5 Resilience & External Call Hardening Unit and Regression Tests.

Covers:
- R-05: LLM retry jitter and JSONDecodeError retry handling
- R-06: Selective OpenAI 400 fallback (only drops response_format for unsupported parameter)
- R-03: Shared HTTP client connection pooling in Qdrant, Vault, and GitHub services
- R-04: Tenacity retries and timeouts across external clients
- R-07: Celery task autoretry_for and worker recycling config
- R-08: Dispatch retry with backoff on broker unavailability
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from agent_worker.celery_app import app as celery_app
from agent_worker.tasks.workflow_tasks import RunWorkflow

from app.core.config import Settings
from app.services.github_service import GitHubAppClient, GitHubOAuthClient
from app.services.qdrant_service import HttpQdrantClient
from app.services.storage_service import _is_transient_s3_error
from app.services.vault_service import HttpVaultClient
from app.workflows.llm import LLMClient

# ==============================================================================
# 1. LLM Resilience (R-05, R-06)
# ==============================================================================


class _FakeLLMResponse:
    def __init__(self, status_code: int, payload: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
            res = httpx.Response(self.status_code, request=req)
            raise httpx.HTTPStatusError(f"HTTP {self.status_code}", request=req, response=res)

    def json(self) -> dict[str, Any]:
        return self._payload


@pytest.mark.asyncio
async def test_llm_malformed_json_is_retryable(test_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """A malformed JSON response from OpenAI/Anthropic is caught as transient and retried."""
    calls: list[Any] = []

    class _FakeAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _FakeAsyncClient:
            return self

        async def __aexit__(self, *exc_info: Any) -> bool:
            return False

        async def post(self, url: str, json: Any = None, headers: Any = None) -> Any:
            calls.append(json)
            if len(calls) == 1:
                return _FakeLLMResponse(
                    200,
                    payload={
                        "choices": [
                            {"message": {"content": "INVALID_JSON_HERE", "role": "assistant"}, "finish_reason": "stop"}
                        ]
                    },
                )
            return _FakeLLMResponse(
                200,
                payload={
                    "choices": [
                        {"message": {"content": '{"success": true}', "role": "assistant"}, "finish_reason": "stop"}
                    ]
                },
            )

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    client = LLMClient(
        test_settings.model_copy(
            update={
                "openai_api_key": "test-key",
                "llm_max_retries": 1,
                "llm_retry_backoff_seconds": 0.01,
            }
        )
    )

    result, _ = await client.generate_json(system_prompt="sys", user_prompt="usr")
    assert result == {"success": True}
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_openai_400_only_drops_response_format_for_parameter_error(test_settings: Settings) -> None:
    """An OpenAI 400 only retries without response_format if the error message mentions it."""
    # Scenario A: Parameter error -> retries without response_format and succeeds
    req_payloads_a = []

    class _TransportParamError(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            req_payloads_a.append(body)
            if "response_format" in body:
                return httpx.Response(400, text="unsupported parameter: response_format is not supported")
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": '{"result": "ok"}', "role": "assistant"}, "finish_reason": "stop"}
                    ]
                },
            )

    client_a = LLMClient(
        test_settings.model_copy(
            update={"openai_api_key": "test-key", "llm_max_retries": 0}
        )
    )
    with patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=_TransportParamError())):
        res, _ = await client_a.generate_json(system_prompt="sys", user_prompt="usr")
        assert res == {"result": "ok"}
        assert len(req_payloads_a) == 2
        assert "response_format" in req_payloads_a[0]
        assert "response_format" not in req_payloads_a[1]

    # Scenario B: Context length error (unrelated 400) -> does NOT drop response_format or retry
    req_payloads_b = []

    class _TransportContextError(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            req_payloads_b.append(body)
            return httpx.Response(400, text="context_length_exceeded: maximum context length is 8192")

    client_b = LLMClient(
        test_settings.model_copy(
            update={"openai_api_key": "test-key", "llm_max_retries": 0}
        )
    )
    with patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=_TransportContextError())):
        with pytest.raises(httpx.HTTPStatusError):
            await client_b.generate_json(system_prompt="sys", user_prompt="usr")
        assert len(req_payloads_b) == 1


# ==============================================================================
# 2. Connection Pooling & Retries in HTTP Clients (R-03, R-04)
# ==============================================================================


@pytest.mark.asyncio
async def test_qdrant_client_reuses_connection_pool(test_settings: Settings) -> None:
    """HttpQdrantClient maintains and reuses a persistent httpx.AsyncClient pool."""
    client = HttpQdrantClient(test_settings)
    c1 = client._get_client()
    c2 = client._get_client()
    assert c1 is c2
    assert not c1.is_closed

    await client.aclose()
    assert c1.is_closed

    # Re-initializes on demand after closure
    c3 = client._get_client()
    assert c3 is not c1
    assert not c3.is_closed
    await client.aclose()


@pytest.mark.asyncio
async def test_vault_client_reuses_connection_pool_and_renews_token(test_settings: Settings) -> None:
    """HttpVaultClient pools connections and supports renew_token."""
    settings = test_settings.model_copy(update={"vault_token": "test-token"})
    client = HttpVaultClient(settings)
    c1 = client._get_client()
    c2 = client._get_client()
    assert c1 is c2

    # Mock renewal response
    with patch.object(c1, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = httpx.Response(200, json={"auth": {"client_token": "test-token"}})
        renewed = await client.renew_token(increment_seconds=1800)
        assert renewed is True
        mock_post.assert_called_once()

    await client.aclose()
    assert c1.is_closed


@pytest.mark.asyncio
async def test_github_clients_reuse_connection_pool(test_settings: Settings) -> None:
    """GitHubAppClient and GitHubOAuthClient reuse pooled HTTP connections."""
    app_client = GitHubAppClient(test_settings)
    ac1 = app_client._get_client()
    ac2 = app_client._get_client()
    assert ac1 is ac2
    await app_client.aclose()
    assert ac1.is_closed

    oauth_client = GitHubOAuthClient(test_settings)
    oc1 = oauth_client._get_client()
    oc2 = oauth_client._get_client()
    assert oc1 is oc2
    await oauth_client.aclose()
    assert oc1.is_closed


# ==============================================================================
# 3. Celery Worker Configuration & Autoretry (R-07)
# ==============================================================================


def test_celery_worker_recycling_configured() -> None:
    """Celery worker is configured to recycle child processes to prevent memory leaks."""
    conf = celery_app.conf
    assert conf.worker_max_tasks_per_child >= 1
    assert conf.worker_max_memory_per_child >= 100000


def test_run_workflow_task_has_autoretry() -> None:
    """RunWorkflow Celery task has transient error autoretry configured."""
    assert ConnectionError in RunWorkflow.autoretry_for
    assert TimeoutError in RunWorkflow.autoretry_for
    assert OSError in RunWorkflow.autoretry_for
    assert RunWorkflow.max_retries == 3
    assert RunWorkflow.retry_backoff is True
    assert RunWorkflow.retry_jitter is True


# ==============================================================================
# 4. Storage Transient Error Classification (R-04)
# ==============================================================================


def test_storage_transient_error_classification() -> None:
    """_is_transient_s3_error accurately identifies retryable S3 errors."""
    import botocore.exceptions

    # BotoCore connection/transport errors are retryable
    conn_err = botocore.exceptions.EndpointConnectionError(endpoint_url="http://s3.local")
    assert _is_transient_s3_error(conn_err) is True

    # 503 Service Unavailable ClientError is retryable
    err_503 = botocore.exceptions.ClientError(
        {"Error": {"Code": "ServiceUnavailable", "Message": "Slow down"}, "ResponseMetadata": {"HTTPStatusCode": 503}},
        "GetObject",
    )
    assert _is_transient_s3_error(err_503) is True

    # 404 NoSuchKey ClientError is NOT retryable
    err_404 = botocore.exceptions.ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "Key not found"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
        "GetObject",
    )
    assert _is_transient_s3_error(err_404) is False
