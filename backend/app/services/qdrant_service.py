"""Qdrant vector store integration for documentation RAG (`Architecture.md §2`, `Database.md §8`).

Implements embedding search with tenant isolation filters (`project_id`, `organization_id`)
and provides an in-memory substitute for tests.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from fastapi import Depends
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.core.metrics import pipeline_error_total

logger = get_logger(__name__)

DEFAULT_COLLECTION = "apiweaver_docs"


class CollectionDimensionMismatchError(RuntimeError):
    """An existing collection's vector size differs from EMBEDDING_DIMENSIONS."""


@dataclass(frozen=True, slots=True)
class ScoredChunk:
    chunk_id: str
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


class QdrantClient(Protocol):
    async def ensure_collection(self, collection_name: str = DEFAULT_COLLECTION) -> None: ...

    async def upsert_chunks(
        self,
        *,
        project_id: uuid.UUID,
        document_id: uuid.UUID,
        chunks: list[dict[str, Any]],
        organization_id: uuid.UUID | None = None,
        collection_name: str = DEFAULT_COLLECTION,
    ) -> None: ...

    async def search(
        self,
        *,
        project_id: uuid.UUID,
        query_vector: list[float],
        limit: int = 5,
        organization_id: uuid.UUID | None = None,
        collection_name: str = DEFAULT_COLLECTION,
    ) -> list[ScoredChunk]: ...

    async def delete_by_document(
        self,
        *,
        project_id: uuid.UUID,
        document_id: uuid.UUID,
        organization_id: uuid.UUID | None = None,
        collection_name: str = DEFAULT_COLLECTION,
    ) -> None: ...


def _is_transient_http_error(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {408, 429, 500, 502, 503, 504}
    return False

_qdrant_retry = retry(
    retry=retry_if_exception(_is_transient_http_error),
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(multiplier=0.1, max=1.5),
    reraise=True,
)


class HttpQdrantClient:
    """Async Qdrant client communicating over the HTTP REST API."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = settings.qdrant_url.rstrip("/")
        self.default_collection = getattr(settings, "qdrant_collection_name", DEFAULT_COLLECTION)
        self.timeout = httpx.Timeout(getattr(settings, "qdrant_timeout_seconds", 10.0))
        self.dimensions = settings.embedding_dimensions
        self._client = client
        self._owns_client = client is None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
            self._owns_client = True
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def __aenter__(self) -> HttpQdrantClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()

    @_qdrant_retry
    async def ensure_collection(self, collection_name: str = DEFAULT_COLLECTION) -> None:
        url = f"{self.base_url}/collections/{collection_name}"
        client = self._get_client()
        try:
            res = await client.get(url)
            if res.status_code == 200:
                vectors = (
                    ((res.json().get("result") or {}).get("config") or {}).get("params") or {}
                ).get("vectors") or {}
                size = vectors.get("size") if isinstance(vectors, dict) else None
                if size is not None and size != self.dimensions:
                    raise CollectionDimensionMismatchError(
                        f"Qdrant collection '{collection_name}' stores {size}-dimensional "
                        f"vectors but EMBEDDING_DIMENSIONS is {self.dimensions}."
                    )
                return
            if res.status_code != 404:
                # A 401/503 is not "missing": creating over it would mask the outage.
                res.raise_for_status()
            payload = {
                "vectors": {
                    "size": self.dimensions,
                    "distance": "Cosine",
                }
            }
            put_res = await client.put(url, json=payload)
            put_res.raise_for_status()
        except Exception as exc:
            pipeline_error_total.labels(subsystem="qdrant", error_type=type(exc).__name__).inc()
            logger.error("qdrant_ensure_collection_failed", error=str(exc), exc_info=True)
            raise

    @_qdrant_retry
    async def upsert_chunks(
        self,
        *,
        project_id: uuid.UUID,
        document_id: uuid.UUID,
        chunks: list[dict[str, Any]],
        organization_id: uuid.UUID | None = None,
        collection_name: str = DEFAULT_COLLECTION,
    ) -> None:
        await self.ensure_collection(collection_name)
        # Delete prior chunks for this document to prevent orphans when chunk count changes (C-10)
        await self.delete_by_document(
            project_id=project_id,
            document_id=document_id,
            organization_id=organization_id,
            collection_name=collection_name,
        )
        if not chunks:
            return

        url = f"{self.base_url}/collections/{collection_name}/points"
        points = []
        doc_uuid = uuid.UUID(str(document_id))
        for idx, chunk in enumerate(chunks):
            # Deterministic uuid5 based on document_id and chunk index (C-09)
            point_id = chunk.get("id") or str(uuid.uuid5(doc_uuid, str(idx)))
            payload: dict[str, Any] = {
                **chunk.get("metadata", {}),
                "project_id": str(project_id),
                "document_id": str(document_id),
                "text": chunk["text"],
            }
            if organization_id:
                payload["organization_id"] = str(organization_id)
            points.append({
                "id": point_id,
                "vector": chunk["vector"],
                "payload": payload,
            })

        batch_size = 100
        client = self._get_client()
        try:
            for i in range(0, len(points), batch_size):
                batch = points[i : i + batch_size]
                res = await client.put(url, json={"points": batch})
                res.raise_for_status()
        except Exception as exc:
            logger.error("qdrant_upsert_failed", error=str(exc))
            raise

    @_qdrant_retry
    async def search(
        self,
        *,
        project_id: uuid.UUID,
        query_vector: list[float],
        limit: int = 5,
        organization_id: uuid.UUID | None = None,
        collection_name: str = DEFAULT_COLLECTION,
    ) -> list[ScoredChunk]:
        url = f"{self.base_url}/collections/{collection_name}/points/search"
        must_filters: list[dict[str, Any]] = [
            {"key": "project_id", "match": {"value": str(project_id)}},
        ]
        if organization_id:
            must_filters.append({"key": "organization_id", "match": {"value": str(organization_id)}})
        payload = {
            "vector": query_vector,
            "limit": limit,
            "filter": {"must": must_filters},
            "with_payload": True,
        }
        client = self._get_client()
        try:
            res = await client.post(url, json=payload)
            if res.status_code == 404:
                return []
            res.raise_for_status()
            data = res.json()
            results = []
            for point in data.get("result", []):
                p_payload = point.get("payload", {})
                results.append(
                    ScoredChunk(
                        chunk_id=str(point.get("id")),
                        text=p_payload.get("text", ""),
                        score=float(point.get("score", 0.0)),
                        metadata=p_payload,
                    )
                )
            return results
        except Exception as exc:
            pipeline_error_total.labels(subsystem="qdrant", error_type=type(exc).__name__).inc()
            logger.error("qdrant_search_failed", error=str(exc), exc_info=True)
            raise

    @_qdrant_retry
    async def delete_by_document(
        self,
        *,
        project_id: uuid.UUID,
        document_id: uuid.UUID,
        organization_id: uuid.UUID | None = None,
        collection_name: str = DEFAULT_COLLECTION,
    ) -> None:
        url = f"{self.base_url}/collections/{collection_name}/points/delete"
        must_filters: list[dict[str, Any]] = [
            {"key": "project_id", "match": {"value": str(project_id)}},
            {"key": "document_id", "match": {"value": str(document_id)}},
        ]
        if organization_id:
            must_filters.append({"key": "organization_id", "match": {"value": str(organization_id)}})
        payload = {"filter": {"must": must_filters}}
        client = self._get_client()
        try:
            res = await client.post(url, json=payload)
            if res.status_code != 404:
                res.raise_for_status()
        except Exception as exc:
            pipeline_error_total.labels(subsystem="qdrant", error_type=type(exc).__name__).inc()
            logger.error("qdrant_delete_failed", error=str(exc), exc_info=True)
            raise


def create_qdrant_client(settings: Settings = Depends(get_settings)) -> QdrantClient:
    return HttpQdrantClient(settings)
