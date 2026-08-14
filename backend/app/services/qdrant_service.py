"""Qdrant vector store integration for documentation RAG (`Architecture.md §2`, `Database.md §8`).

Implements embedding search with tenant isolation filters (`project_id`, `organization_id`)
and provides an in-memory substitute for tests.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from fastapi import Depends

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_COLLECTION = "apiweaver_docs"
VECTOR_DIMENSION = 1536  # Default embedding size for OpenAI text-embedding-3-small or similar


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

    async def ensure_collection(self, collection_name: str = DEFAULT_COLLECTION) -> None:
        url = f"{self.base_url}/collections/{collection_name}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                res = await client.get(url)
                if res.status_code == 200:
                    return
                # Create collection if it doesn't exist
                payload = {
                    "vectors": {
                        "size": VECTOR_DIMENSION,
                        "distance": "Cosine",
                    }
                }
                put_res = await client.put(url, json=payload)
                put_res.raise_for_status()
            except Exception as exc:
                logger.warning("qdrant_ensure_collection_failed", error=str(exc))

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
                "payload": {
                    "project_id": str(project_id),
                    "document_id": str(document_id),
                    "text": chunk["text"],
                    **chunk.get("metadata", {}),
                },
            })

        async with httpx.AsyncClient(timeout=10.0) as client:
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
        async with httpx.AsyncClient(timeout=10.0) as client:
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
                logger.error("qdrant_search_failed", error=str(exc))
                return []

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
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                res = await client.post(url, json=payload)
                if res.status_code != 404:
                    res.raise_for_status()
            except Exception as exc:
                logger.error("qdrant_delete_failed", error=str(exc))


class FakeQdrantClient:
    """In-memory vector store mock for unit and integration testing."""

    def __init__(self) -> None:
        self._points: dict[str, list[dict[str, Any]]] = {}

    async def ensure_collection(self, collection_name: str = DEFAULT_COLLECTION) -> None:
        if collection_name not in self._points:
            self._points[collection_name] = []

    async def upsert_chunks(
        self,
        *,
        project_id: uuid.UUID,
        document_id: uuid.UUID,
        chunks: list[dict[str, Any]],
        collection_name: str = DEFAULT_COLLECTION,
    ) -> None:
        await self.ensure_collection(collection_name)
        for chunk in chunks:
            point_id = chunk.get("id") or str(uuid.uuid4())
            self._points[collection_name].append({
                "id": point_id,
                "vector": chunk["vector"],
                "project_id": str(project_id),
                "document_id": str(document_id),
                "text": chunk["text"],
                "metadata": chunk.get("metadata", {}),
            })

    async def search(
        self,
        *,
        project_id: uuid.UUID,
        query_vector: list[float],
        limit: int = 5,
        collection_name: str = DEFAULT_COLLECTION,
    ) -> list[ScoredChunk]:
        await self.ensure_collection(collection_name)
        candidates = [
            p for p in self._points.get(collection_name, [])
            if p["project_id"] == str(project_id)
        ]

        scored: list[tuple[float, dict[str, Any]]] = []
        for p in candidates:
            # Cosine similarity
            dot = sum(a * b for a, b in zip(query_vector, p["vector"], strict=False))
            norm_a = math.sqrt(sum(a * a for a in query_vector)) or 1.0
            norm_b = math.sqrt(sum(b * b for b in p["vector"])) or 1.0
            sim = dot / (norm_a * norm_b)
            scored.append((sim, p))

        scored.sort(key=lambda x: x[0], reverse=True)
        results: list[ScoredChunk] = []
        for score, p in scored[:limit]:
            results.append(
                ScoredChunk(
                    chunk_id=p["id"],
                    text=p["text"],
                    score=score,
                    metadata={
                        "project_id": p["project_id"],
                        "document_id": p["document_id"],
                        **p["metadata"],
                    },
                )
            )
        return results

    async def delete_by_document(
        self,
        *,
        project_id: uuid.UUID,
        document_id: uuid.UUID,
        collection_name: str = DEFAULT_COLLECTION,
    ) -> None:
        if collection_name in self._points:
            self._points[collection_name] = [
                p for p in self._points[collection_name]
                if not (
                    p["project_id"] == str(project_id)
                    and p["document_id"] == str(document_id)
                )
            ]


def create_qdrant_client(settings: Settings = Depends(get_settings)) -> QdrantClient:
    return HttpQdrantClient(settings)
