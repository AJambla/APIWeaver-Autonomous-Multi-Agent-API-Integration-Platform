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
        collection_name: str = DEFAULT_COLLECTION,
    ) -> None: ...

    async def search(
        self,
        *,
        project_id: uuid.UUID,
        query_vector: list[float],
        limit: int = 5,
        collection_name: str = DEFAULT_COLLECTION,
    ) -> list[ScoredChunk]: ...

    async def delete_by_document(
        self,
        *,
        project_id: uuid.UUID,
        document_id: uuid.UUID,
        collection_name: str = DEFAULT_COLLECTION,
    ) -> None: ...


class HttpQdrantClient:
    """Async Qdrant client communicating over the HTTP REST API."""

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.qdrant_url.rstrip("/")
        self.timeout = getattr(settings, "qdrant_timeout_seconds", 10.0)
        self.dimensions = settings.embedding_dimensions

    async def ensure_collection(self, collection_name: str = DEFAULT_COLLECTION) -> None:
        url = f"{self.base_url}/collections/{collection_name}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
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

    async def upsert_chunks(
        self,
        *,
        project_id: uuid.UUID,
        document_id: uuid.UUID,
        chunks: list[dict[str, Any]],
        collection_name: str = DEFAULT_COLLECTION,
    ) -> None:
        await self.ensure_collection(collection_name)
        url = f"{self.base_url}/collections/{collection_name}/points"
        points = []
        for chunk in chunks:
            point_id = chunk.get("id") or str(uuid.uuid4())
            points.append({
                "id": point_id,
                "vector": chunk["vector"],
                # Tenant keys last: chunk metadata must never overwrite project_id, the
                # key every search filters on.
                "payload": {
                    **chunk.get("metadata", {}),
                    "project_id": str(project_id),
                    "document_id": str(document_id),
                    "text": chunk["text"],
                },
            })

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                res = await client.put(url, json={"points": points})
                res.raise_for_status()
            except Exception as exc:
                logger.error("qdrant_upsert_failed", error=str(exc))
                raise

    async def search(
        self,
        *,
        project_id: uuid.UUID,
        query_vector: list[float],
        limit: int = 5,
        collection_name: str = DEFAULT_COLLECTION,
    ) -> list[ScoredChunk]:
        url = f"{self.base_url}/collections/{collection_name}/points/search"
        payload = {
            "vector": query_vector,
            "limit": limit,
            "filter": {
                "must": [
                    {"key": "project_id", "match": {"value": str(project_id)}},
                ]
            },
            "with_payload": True,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
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

    async def delete_by_document(
        self,
        *,
        project_id: uuid.UUID,
        document_id: uuid.UUID,
        collection_name: str = DEFAULT_COLLECTION,
    ) -> None:
        url = f"{self.base_url}/collections/{collection_name}/points/delete"
        payload = {
            "filter": {
                "must": [
                    {"key": "project_id", "match": {"value": str(project_id)}},
                    {"key": "document_id", "match": {"value": str(document_id)}},
                ]
            }
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
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
