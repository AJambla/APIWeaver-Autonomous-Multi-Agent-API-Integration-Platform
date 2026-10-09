"""In-memory test doubles and fakes for external services (Vault, Qdrant, S3).

These fakes are exclusively for test isolation and must never be referenced by production runtime code.
"""

from __future__ import annotations

import math
import uuid
from typing import Any

from app.services.qdrant_service import DEFAULT_COLLECTION, ScoredChunk
from app.services.storage_service import validate_storage_key
from app.services.vault_service import validate_vault_path


class FakeVaultClient:
    """In-memory mock Vault client for testing."""

    def __init__(self) -> None:
        self._secrets: dict[str, dict[str, Any]] = {}

    async def write_secret(self, path: str, data: dict[str, Any]) -> None:
        clean_path = validate_vault_path(path)
        self._secrets[clean_path] = dict(data)

    async def read_secret(self, path: str) -> dict[str, Any] | None:
        clean_path = validate_vault_path(path)
        data = self._secrets.get(clean_path)
        return dict(data) if data is not None else None

    async def delete_secret(self, path: str) -> None:
        clean_path = validate_vault_path(path)
        self._secrets.pop(clean_path, None)


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
        organization_id: uuid.UUID | None = None,
        collection_name: str = DEFAULT_COLLECTION,
    ) -> None:
        await self.ensure_collection(collection_name)
        await self.delete_by_document(
            project_id=project_id,
            document_id=document_id,
            organization_id=organization_id,
            collection_name=collection_name,
        )
        doc_uuid = uuid.UUID(str(document_id))
        for idx, chunk in enumerate(chunks):
            point_id = chunk.get("id") or str(uuid.uuid5(doc_uuid, str(idx)))
            self._points[collection_name].append({
                "id": point_id,
                "vector": chunk["vector"],
                "project_id": str(project_id),
                "document_id": str(document_id),
                "organization_id": str(organization_id) if organization_id else None,
                "text": chunk["text"],
                "metadata": chunk.get("metadata", {}),
            })

    async def search(
        self,
        *,
        project_id: uuid.UUID,
        query_vector: list[float],
        limit: int = 5,
        organization_id: uuid.UUID | None = None,
        collection_name: str = DEFAULT_COLLECTION,
    ) -> list[ScoredChunk]:
        await self.ensure_collection(collection_name)
        candidates = [
            p for p in self._points.get(collection_name, [])
            if p["project_id"] == str(project_id)
            and (organization_id is None or p.get("organization_id") == str(organization_id))
        ]

        scored: list[tuple[float, dict[str, Any]]] = []
        for p in candidates:
            dot = sum(a * b for a, b in zip(query_vector, p["vector"], strict=False))
            norm_a = math.sqrt(sum(a * a for a in query_vector)) or 1.0
            norm_b = math.sqrt(sum(b * b for b in p["vector"])) or 1.0
            sim = dot / (norm_a * norm_b)
            scored.append((sim, p))

        scored.sort(key=lambda x: x[0], reverse=True)
        results: list[ScoredChunk] = []
        for score, p in scored[:limit]:
            metadata = {
                "project_id": p["project_id"],
                "document_id": p["document_id"],
                **p["metadata"],
            }
            if p.get("organization_id"):
                metadata["organization_id"] = p["organization_id"]
            results.append(
                ScoredChunk(
                    chunk_id=p["id"],
                    text=p["text"],
                    score=score,
                    metadata=metadata,
                )
            )
        return results

    async def delete_by_document(
        self,
        *,
        project_id: uuid.UUID,
        document_id: uuid.UUID,
        organization_id: uuid.UUID | None = None,
        collection_name: str = DEFAULT_COLLECTION,
    ) -> None:
        if collection_name in self._points:
            self._points[collection_name] = [
                p for p in self._points[collection_name]
                if not (
                    p["project_id"] == str(project_id)
                    and p["document_id"] == str(document_id)
                    and (organization_id is None or p.get("organization_id") == str(organization_id))
                )
            ]


class InMemoryObjectStorage:
    """In-memory object storage fallback for tests."""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    async def get(self, *, key: str, bucket: str | None = None) -> bytes | None:
        key = validate_storage_key(key)
        return self._store.get(key)

    async def put(self, *, key: str, content: bytes, content_type: str | None = None, bucket: str | None = None) -> None:
        key = validate_storage_key(key)
        self._store[key] = content

    async def delete(self, *, key: str, bucket: str | None = None) -> None:
        key = validate_storage_key(key)
        self._store.pop(key, None)

    async def upload(self, key: str, content: bytes, bucket: str | None = None) -> None:
        await self.put(key=key, content=content, content_type="text/plain", bucket=bucket)

    async def download(self, key: str, bucket: str | None = None) -> bytes:
        result = await self.get(key=key, bucket=bucket)
        if result is None:
            raise FileNotFoundError(f"Object not found: {key}")
        return result
