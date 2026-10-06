"""Tests for Qdrant embedding pipeline."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.services.chunker import chunk_text
from app.services.document_parser import extract_text
from app.services.qdrant_service import FakeQdrantClient, ScoredChunk
from app.core.errors import DependencyUnavailableError
from app.workflows.agents.doc_agent import _upsert_to_qdrant, run_doc_agent
from app.workflows.llm import LLMClient
from app.workflows.state import WorkflowState


class TestChunkText:
    def test_chunk_text_basic(self):
        text = "A" * 1000
        chunks = chunk_text(text, chunk_size=500, overlap=50)
        # With 1000 chars, chunk_size=500, overlap=50:
        # Chunk 1: 0-500, Chunk 2: 450-950, Chunk 3: 900-1000
        assert len(chunks) == 3
        assert len(chunks[0]) == 500
        assert len(chunks[1]) == 500
        assert len(chunks[2]) == 100

    def test_chunk_text_short(self):
        text = "Short text"
        chunks = chunk_text(text, chunk_size=500, overlap=50)
        assert len(chunks) == 1
        assert chunks[0] == "Short text"

    def test_chunk_text_empty(self):
        chunks = chunk_text("")
        assert chunks == []

    def test_chunk_text_overlap(self):
        text = "A" * 600
        chunks = chunk_text(text, chunk_size=500, overlap=100)
        assert len(chunks) == 2
        # Second chunk should start at position 400 (500 - 100)
        assert chunks[1] == "A" * 200

    def test_chunk_text_invalid_params(self):
        with pytest.raises(ValueError):
            chunk_text("text", chunk_size=0)
        with pytest.raises(ValueError):
            chunk_text("text", overlap=-1)
        with pytest.raises(ValueError):
            chunk_text("text", chunk_size=100, overlap=100)


class TestExtractText:
    def test_extract_markdown(self):
        content = b"# Header\n\nSome text"
        result = extract_text(content, "doc.md")
        assert "# Header" in result
        assert "Some text" in result

    def test_extract_text_file(self):
        content = b"Plain text content"
        result = extract_text(content, "notes.txt")
        assert result == "Plain text content"

    def test_extract_html(self):
        content = b"<html><body><h1>Title</h1><p>Paragraph</p></body></html>"
        result = extract_text(content, "doc.html")
        assert "Title" in result
        assert "Paragraph" in result

    def test_extract_pdf(self):
        # Test that PDF extraction doesn't crash (falls back to UTF-8 for invalid PDF)
        content = b"%PDF-1.4\n%Test content"
        # This will fail and fall back to UTF-8 decode
        result = extract_text(content, "doc.pdf")
        # Should not crash, returns fallback text
        assert isinstance(result, str)
        assert "Test content" in result


class TestFakeQdrantClient:
    @pytest.fixture
    def fake_client(self) -> FakeQdrantClient:
        return FakeQdrantClient()

    @pytest.mark.asyncio
    async def test_upsert_and_search(self, fake_client: FakeQdrantClient):
        project_id = uuid.uuid4()
        document_id = uuid.uuid4()
        vector = [0.1] * 1536

        await fake_client.upsert_chunks(
            project_id=project_id,
            document_id=document_id,
            chunks=[{"text": "Test chunk", "vector": vector}],
        )

        results = await fake_client.search(
            project_id=project_id,
            query_vector=vector,
            limit=5,
        )

        assert len(results) == 1
        assert isinstance(results[0], ScoredChunk)
        assert results[0].text == "Test chunk"
        assert results[0].score > 0.9  # Should be very similar

    @pytest.mark.asyncio
    async def test_upsert_multiple_chunks(self, fake_client: FakeQdrantClient):
        project_id = uuid.uuid4()
        document_id = uuid.uuid4()
        vectors = [[float(i)] * 1536 for i in range(3)]

        await fake_client.upsert_chunks(
            project_id=project_id,
            document_id=document_id,
            chunks=[{"text": f"Chunk {i}", "vector": vectors[i]} for i in range(3)],
        )

        results = await fake_client.search(
            project_id=project_id,
            query_vector=vectors[1],
            limit=5,
        )

        assert len(results) == 3
        # Best match should be chunk 1
        assert results[0].text == "Chunk 1"

    @pytest.mark.asyncio
    async def test_delete_by_document(self, fake_client: FakeQdrantClient):
        project_id = uuid.uuid4()
        document_id = uuid.uuid4()
        vector = [0.1] * 1536

        await fake_client.upsert_chunks(
            project_id=project_id,
            document_id=document_id,
            chunks=[{"text": "Test", "vector": vector}],
        )

        await fake_client.delete_by_document(
            project_id=project_id,
            document_id=document_id,
        )

        results = await fake_client.search(
            project_id=project_id,
            query_vector=vector,
            limit=5,
        )

        assert len(results) == 0


class TestLLMClientEmbedding:
    @pytest.mark.asyncio
    async def test_generate_embedding_mock(self):
        client = LLMClient()
        if not client.settings.openai_api_key:
            with pytest.raises(DependencyUnavailableError):
                await client.generate_embedding("test text")
        else:
            embedding = await client.generate_embedding("test text")
            assert len(embedding) == 1536


class TestRunDocAgentWithQdrant:
    @pytest.mark.asyncio
    async def test_run_doc_agent_upserts_to_qdrant(self):
        """Test that doc_agent calls Qdrant upsert when client provided."""
        fake_qdrant = FakeQdrantClient()
        state: WorkflowState = {
            "project_id": str(uuid.uuid4()),
            "organization_id": str(uuid.uuid4()),
            "workflow_run_id": str(uuid.uuid4()),
            "document_id": str(uuid.uuid4()),
            "document_filename": "api.md",
            "raw_document_bytes": b"# API\nGET /test - Test endpoint",
            "stages": ["plan"],
        }

        result = await run_doc_agent(state, qdrant_client=fake_qdrant)

        assert result["status"] == "spec_ready"
        assert result["normalized_spec"] is not None

        # Verify Qdrant was called
        search_results = await fake_qdrant.search(
            project_id=uuid.UUID(state["project_id"]),
            query_vector=[0.0] * 1536,
            limit=5,
        )
        assert len(search_results) > 0


class TestEmbeddingChunkCap:
    @pytest.mark.asyncio
    async def test_upsert_stops_at_the_configured_cap(self, monkeypatch) -> None:
        """One upload may be `max_upload_bytes` large; embedding calls must not scale
        with it without a ceiling (audit M8)."""
        embedded: list[str] = []

        async def fake_generate_embedding(chunk: str) -> list[float]:
            embedded.append(chunk)
            return [0.0] * 1536

        client = LLMClient()
        client.settings = client.settings.model_copy(update={"max_embedding_chunks": 3})
        monkeypatch.setattr(client, "generate_embedding", fake_generate_embedding)

        fake_qdrant = FakeQdrantClient()
        project_id, document_id = uuid.uuid4(), uuid.uuid4()
        state: WorkflowState = {
            "project_id": str(project_id),
            "document_id": str(document_id),
        }
        long_text = " ".join(f"Endpoint number {i} returns data." for i in range(400))
        assert len(chunk_text(long_text)) > 3

        await _upsert_to_qdrant(fake_qdrant, client, state, long_text)  # type: ignore[arg-type]

        assert len(embedded) == 3
        stored = await fake_qdrant.search(
            project_id=project_id, query_vector=[0.0] * 1536, limit=50
        )
        assert len(stored) == 3