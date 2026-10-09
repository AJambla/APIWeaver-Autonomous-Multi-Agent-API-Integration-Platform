"""Phase 3 Data Layer Correctness unit and regression tests.

Covers:
- Object storage bucket routing and content-type inference (C-08, Hardcoded)
- Qdrant deterministic IDs, prior chunk cleanup, tenant isolation, batching (C-09, C-10, X-06, S-04)
- LLM client batch embeddings (S-04)
- Document upload streaming size enforcement (C-12, S-05)
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.core.config import Settings, get_settings
from app.services.storage_service import AsyncS3ObjectStorage, validate_storage_key
from app.workflows.llm import LLMClient
from tests.fakes import FakeQdrantClient

# ==============================================================================
# 1. Object Storage Tests
# ==============================================================================


class TestStorageRoutingAndMimeTypes:
    @pytest.fixture
    def settings(self) -> Settings:
        return Settings(
            s3_bucket_uploads="app-uploads",
            s3_bucket_artifacts="app-artifacts",
            s3_endpoint_url="http://localhost:9000",
            aws_access_key_id="test-key",
            aws_secret_access_key="test-secret",
            database_url="sqlite+aiosqlite:///:memory:",
            redis_url="redis://localhost:6379/0",
            jwt_private_key_path="jwt_keys/private.pem",
            jwt_public_key_path="jwt_keys/public.pem",
        )

    def test_storage_key_validation(self) -> None:
        assert validate_storage_key("projects/123/documents/spec.json") == "projects/123/documents/spec.json"
        assert validate_storage_key("/documents/spec.json") == "documents/spec.json"
        assert validate_storage_key("documents\\spec.json") == "documents/spec.json"

        with pytest.raises(ValueError, match="Invalid or unsafe storage key"):
            validate_storage_key("../secret.txt")

        with pytest.raises(ValueError, match="Invalid or unsafe storage key"):
            validate_storage_key("projects/../../secret.txt")

    def test_bucket_routing(self, settings: Settings) -> None:
        with patch("aiobotocore.session.get_session"):
            storage = AsyncS3ObjectStorage(settings)

            # Documents and uploads route to uploads bucket
            assert storage._target_bucket_for_key("documents/spec.yaml") == "app-uploads"
            assert storage._target_bucket_for_key("uploads/file.txt") == "app-uploads"
            assert storage._target_bucket_for_key("projects/123/documents/spec.json") == "app-uploads"

            # Artifacts, exports, and generated files route to artifacts bucket
            assert storage._target_bucket_for_key("exports/bundle.zip") == "app-artifacts"
            assert storage._target_bucket_for_key("artifacts/output.json") == "app-artifacts"
            assert storage._target_bucket_for_key("projects/123/artifacts/client.zip") == "app-artifacts"
            assert storage._target_bucket_for_key("generated/sdk/python.tar.gz") == "app-artifacts"

            # Explicit bucket argument overrides routing
            assert storage._target_bucket_for_key("documents/spec.yaml", bucket="custom-bucket") == "custom-bucket"
            assert storage._target_bucket_for_key("exports/bundle.zip", bucket="custom-bucket") == "custom-bucket"

    @pytest.mark.asyncio
    async def test_put_and_upload_content_type_inference(self, settings: Settings) -> None:
        with patch("aiobotocore.session.get_session"):
            storage = AsyncS3ObjectStorage(settings)

            mock_client = AsyncMock()
            mock_client_context = AsyncMock()
            mock_client_context.__aenter__.return_value = mock_client
            mock_client_context.__aexit__.return_value = None

            storage._get_client = AsyncMock(return_value=mock_client_context)  # type: ignore[method-assign]

            # Put JSON without explicit content-type
            await storage.put(key="projects/1/documents/spec.json", content=b"{}")
            mock_client.put_object.assert_called_with(
                Bucket="app-uploads",
                Key="projects/1/documents/spec.json",
                Body=b"{}",
                ContentType="application/json",
            )

            # Put ZIP archive
            await storage.put(key="exports/sdk.zip", content=b"PK\x03\x04")
            call_kwargs = mock_client.put_object.call_args.kwargs
            assert call_kwargs["Bucket"] == "app-artifacts"
            assert call_kwargs["Key"] == "exports/sdk.zip"
            assert call_kwargs["Body"] == b"PK\x03\x04"
            assert call_kwargs["ContentType"] in ("application/zip", "application/x-zip-compressed")

            # Put with explicit content-type override
            await storage.put(key="exports/sdk.zip", content=b"PK\x03\x04", content_type="application/octet-stream")
            mock_client.put_object.assert_called_with(
                Bucket="app-artifacts",
                Key="exports/sdk.zip",
                Body=b"PK\x03\x04",
                ContentType="application/octet-stream",
            )


# ==============================================================================
# 2. Qdrant Deduplication, Deterministic IDs & Tenant Isolation
# ==============================================================================


class TestQdrantPhase3Enhancements:
    @pytest.fixture
    def client(self) -> FakeQdrantClient:
        return FakeQdrantClient()

    @pytest.mark.asyncio
    async def test_reprocessing_cleans_old_chunks(self, client: FakeQdrantClient) -> None:
        project_id = uuid.uuid4()
        doc_id = uuid.uuid4()

        # Initial upsert: 3 chunks
        chunks_v1 = [
            {"text": f"V1 chunk {i}", "vector": [0.1] * 1536}
            for i in range(3)
        ]
        await client.upsert_chunks(
            project_id=project_id,
            document_id=doc_id,
            chunks=chunks_v1,
        )

        results_v1 = await client.search(project_id=project_id, query_vector=[0.1] * 1536, limit=10)
        assert len(results_v1) == 3
        assert {c.text for c in results_v1} == {"V1 chunk 0", "V1 chunk 1", "V1 chunk 2"}

        # Reprocess document with 2 new chunks
        chunks_v2 = [
            {"text": f"V2 chunk {i}", "vector": [0.1] * 1536}
            for i in range(2)
        ]
        await client.upsert_chunks(
            project_id=project_id,
            document_id=doc_id,
            chunks=chunks_v2,
        )

        # Old chunks must be purged, only V2 chunks remain
        results_v2 = await client.search(project_id=project_id, query_vector=[0.1] * 1536, limit=10)
        assert len(results_v2) == 2
        assert {c.text for c in results_v2} == {"V2 chunk 0", "V2 chunk 1"}

    @pytest.mark.asyncio
    async def test_deterministic_chunk_ids(self, client: FakeQdrantClient) -> None:
        project_id = uuid.uuid4()
        doc_id = uuid.uuid4()

        chunks = [{"text": "Deterministic chunk", "vector": [0.2] * 1536}]
        await client.upsert_chunks(
            project_id=project_id,
            document_id=doc_id,
            chunks=chunks,
        )

        expected_id = str(uuid.uuid5(doc_id, "0"))
        results = await client.search(project_id=project_id, query_vector=[0.2] * 1536, limit=1)
        assert len(results) == 1
        assert results[0].chunk_id == expected_id

    @pytest.mark.asyncio
    async def test_tenant_isolation_with_organization_id(self, client: FakeQdrantClient) -> None:
        project_id = uuid.uuid4()
        org_a = uuid.uuid4()
        org_b = uuid.uuid4()
        doc_a = uuid.uuid4()
        doc_b = uuid.uuid4()

        # Org A chunks
        await client.upsert_chunks(
            project_id=project_id,
            document_id=doc_a,
            organization_id=org_a,
            chunks=[{"text": "Org A secret", "vector": [0.3] * 1536}],
        )

        # Org B chunks
        await client.upsert_chunks(
            project_id=project_id,
            document_id=doc_b,
            organization_id=org_b,
            chunks=[{"text": "Org B secret", "vector": [0.3] * 1536}],
        )

        # Search scoped to Org A must NOT see Org B
        results_a = await client.search(
            project_id=project_id,
            organization_id=org_a,
            query_vector=[0.3] * 1536,
            limit=10,
        )
        assert len(results_a) == 1
        assert results_a[0].text == "Org A secret"

        # Search scoped to Org B must NOT see Org A
        results_b = await client.search(
            project_id=project_id,
            organization_id=org_b,
            query_vector=[0.3] * 1536,
            limit=10,
        )
        assert len(results_b) == 1
        assert results_b[0].text == "Org B secret"


# ==============================================================================
# 3. LLM Client Batch Embeddings
# ==============================================================================


class TestLLMBatchEmbeddings:
    @pytest.mark.asyncio
    async def test_batch_embeddings_100_chunking(self, test_settings: Settings) -> None:
        settings = test_settings.model_copy(
            update={
                "openai_api_key": "test-key",
                "embedding_base_url": "http://embeddings.test/v1",
                "embedding_dimensions": 4,
                "llm_max_retries": 0,
            }
        )
        client = LLMClient(settings)

        batch_calls: list[list[str]] = []

        async def fake_provider(provider: str, send_fn: Any) -> list[list[float]]:
            # Emulate the response from send_fn
            return await send_fn()

        client._call_provider = AsyncMock(side_effect=fake_provider)  # type: ignore[method-assign]
        texts = [f"sample text {i}" for i in range(250)]

        # Mock the underlying HTTP request
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient.post") as mock_post:
            def side_effect(url: str, json: dict[str, Any], headers: dict[str, str]) -> Any:
                input_texts = json["input"]
                batch_calls.append(input_texts)
                resp = MagicMock()
                resp.status_code = 200
                resp.json.return_value = {
                    "data": [
                        {"index": i, "embedding": [0.1, 0.2, 0.3, 0.4]}
                        for i in range(len(input_texts))
                    ]
                }
                return resp

            mock_post.side_effect = side_effect

            embeddings = await client.generate_embeddings(texts)

            assert len(embeddings) == 250
            # 250 texts should be batched into 100, 100, 50
            assert len(batch_calls) == 3
            assert len(batch_calls[0]) == 100
            assert len(batch_calls[1]) == 100
            assert len(batch_calls[2]) == 50


# ==============================================================================
# 4. Document Upload Streaming Limits
# ==============================================================================


class TestDocumentUploadStreaming:
    @pytest.mark.asyncio
    async def test_upload_exceeds_max_bytes_returns_413(
        self, client: AsyncClient, app: Any, test_settings: Settings
    ) -> None:
        # Register and login
        reg_res = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "stream_test@example.com",
                "password": "Password123!",
                "full_name": "Stream Tester",
                "organization_name": "Stream Org",
            },
        )
        assert reg_res.status_code == 201
        token = reg_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        me = await client.get("/api/v1/auth/me", headers=headers)
        org_id = me.json()["organizations"][0]["organization_id"]

        # Create project
        proj_res = await client.post(
            "/api/v1/projects",
            json={"name": "Stream Test Project", "organization_id": org_id},
            headers=headers,
        )
        assert proj_res.status_code == 201
        project_id = proj_res.json()["id"]

        # Oversized content with settings max_upload_bytes = 100
        app.dependency_overrides[get_settings] = lambda: test_settings.model_copy(
            update={"max_upload_bytes": 100}
        )
        try:
            oversized_data = b"x" * 200
            files = {"file": ("big_doc.txt", oversized_data, "text/plain")}
            upload_res = await client.post(
                f"/api/v1/projects/{project_id}/upload",
                headers=headers,
                files=files,
            )
            assert upload_res.status_code == 413
            data = upload_res.json()
            assert data["error"]["code"] == "PAYLOAD_TOO_LARGE"
            assert "File size exceeds limit of 100 bytes" in data["error"]["message"]
        finally:
            app.dependency_overrides[get_settings] = lambda: test_settings
