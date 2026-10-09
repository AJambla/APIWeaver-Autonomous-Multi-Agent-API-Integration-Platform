"""A wrong embedding size must fail loudly, not silently disable retrieval."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest

from app.services.qdrant_service import CollectionDimensionMismatchError, HttpQdrantClient
from app.workflows.llm import EmbeddingDimensionMismatchError, LLMClient


def _route(monkeypatch, handler) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    class _Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

    original = httpx.AsyncClient

    def _client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = _Transport()
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _client)
    return seen


def _llm(test_settings, **overrides) -> LLMClient:
    return LLMClient(
        test_settings.model_copy(
            update={
                "embedding_base_url": "http://embeddings.test/v1",
                "openai_api_key": "k",
                "llm_max_retries": 0,
                **overrides,
            }
        )
    )


async def test_a_vector_of_the_wrong_size_is_an_explicit_error(monkeypatch, test_settings) -> None:
    _route(monkeypatch, lambda r: httpx.Response(200, json={"data": [{"embedding": [0.1] * 768}]}))

    with pytest.raises(EmbeddingDimensionMismatchError, match="EMBEDDING_DIMENSIONS to 768"):
        await _llm(test_settings).generate_embedding("hello")


async def test_an_unrelated_400_is_not_retried_without_dimensions(monkeypatch, test_settings) -> None:
    seen = _route(monkeypatch, lambda r: httpx.Response(400, json={"error": "input too long"}))

    with pytest.raises(httpx.HTTPStatusError):
        await _llm(test_settings).generate_embedding("hello")
    assert len(seen) == 1


async def test_a_provider_rejecting_dimensions_is_retried_without_it(monkeypatch, test_settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "dimensions" in json.loads(request.content):
            return httpx.Response(400, json={"error": "unknown parameter: dimensions"})
        return httpx.Response(200, json={"data": [{"embedding": [0.1] * 1536}]})

    seen = _route(monkeypatch, handler)

    vector = await _llm(test_settings).generate_embedding("hello")
    assert len(vector) == 1536 and len(seen) == 2


async def test_an_existing_collection_of_another_size_is_refused(monkeypatch, test_settings) -> None:
    _route(
        monkeypatch,
        lambda r: httpx.Response(
            200, json={"result": {"config": {"params": {"vectors": {"size": 768, "distance": "Cosine"}}}}}
        ),
    )

    with pytest.raises(CollectionDimensionMismatchError):
        await HttpQdrantClient(test_settings).ensure_collection()


async def test_an_unavailable_qdrant_is_not_mistaken_for_a_missing_collection(
    monkeypatch, test_settings
) -> None:
    seen = _route(monkeypatch, lambda r: httpx.Response(503))

    with pytest.raises(httpx.HTTPStatusError):
        await HttpQdrantClient(test_settings).ensure_collection()
    assert all(r.method == "GET" for r in seen) and len(seen) >= 1


async def test_a_missing_collection_is_created_with_the_configured_size(
    monkeypatch, test_settings
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404) if request.method == "GET" else httpx.Response(200, json={})

    seen = _route(monkeypatch, handler)
    settings = test_settings.model_copy(update={"embedding_dimensions": 1024})

    await HttpQdrantClient(settings).ensure_collection()
    assert json.loads(seen[1].content)["vectors"]["size"] == 1024


async def test_chunk_metadata_cannot_overwrite_the_tenant_key(monkeypatch, test_settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200, json={"result": {"config": {"params": {"vectors": {"size": 1536}}}}}
            )
        return httpx.Response(200, json={})

    seen = _route(monkeypatch, handler)
    project_id = uuid.uuid4()

    await HttpQdrantClient(test_settings).upsert_chunks(
        project_id=project_id,
        document_id=uuid.uuid4(),
        chunks=[{"text": "t", "vector": [0.0] * 1536, "metadata": {"project_id": "someone-else"}}],
    )
    payload = json.loads(seen[-1].content)["points"][0]["payload"]
    assert payload["project_id"] == str(project_id)
