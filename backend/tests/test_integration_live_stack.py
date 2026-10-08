"""Integration tests against live containerized services (Postgres, Redis, Qdrant, MinIO, Vault).

Covers I/O boundaries, connection pooling, transactional rollbacks, vector indexing,
secret management, and object storage against actual running infrastructure.
"""

from __future__ import annotations

import asyncio
import os
import socket
import time
import uuid
from typing import Any

import httpx
import pytest
import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.services.qdrant_service import HttpQdrantClient, VECTOR_DIMENSION
from app.services.storage_service import AsyncS3ObjectStorage
from app.services.vault_service import HttpVaultClient

# Default service URLs matching the local Docker compose stack
LIVE_PG_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://apiweaver:apiweaver@127.0.0.1:5432/apiweaver",
)
LIVE_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6379/0")
LIVE_QDRANT_URL = os.environ.get("TEST_QDRANT_URL", "http://127.0.0.1:6333")
LIVE_VAULT_ADDR = os.environ.get("TEST_VAULT_ADDR", "http://127.0.0.1:8200")
LIVE_VAULT_TOKEN = os.environ.get("TEST_VAULT_TOKEN", "root")
LIVE_S3_ENDPOINT = os.environ.get("TEST_S3_ENDPOINT_URL", "http://127.0.0.1:9000")
LIVE_AWS_KEY = os.environ.get("TEST_AWS_ACCESS_KEY_ID", "minioadmin")
LIVE_AWS_SECRET = os.environ.get("TEST_AWS_SECRET_ACCESS_KEY", "minioadmin")


def _is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _is_service_reachable(url: str) -> bool:
    try:
        res = httpx.get(url, timeout=1.5)
        return res.status_code in (200, 404)
    except Exception:
        return False


def is_postgres_available() -> bool:
    return _is_port_open("127.0.0.1", 5432)


def is_redis_available() -> bool:
    return _is_port_open("127.0.0.1", 6379)


def is_qdrant_available() -> bool:
    return _is_service_reachable(f"{LIVE_QDRANT_URL}/readyz")


def is_vault_available() -> bool:
    return _is_service_reachable(f"{LIVE_VAULT_ADDR}/v1/sys/health")


def is_minio_available() -> bool:
    return _is_service_reachable(f"{LIVE_S3_ENDPOINT}/minio/health/live")


pytestmark = pytest.mark.integration


# ==============================================================================
# 1. PostgreSQL Integration Tests: Transactions, Rollbacks, Pool Lifecycle
# ==============================================================================
@pytest.mark.skipif(not is_postgres_available(), reason="PostgreSQL not available at 127.0.0.1:5432")
class TestPostgresIntegration:
    """Exercises real PostgreSQL connections, ACID transactions, and rollback behavior."""

    @pytest.fixture
    async def pg_engine(self):
        engine = create_async_engine(LIVE_PG_URL, pool_size=5, max_overflow=2)
        yield engine
        await engine.dispose()

    async def test_postgres_connection_and_version(self, pg_engine):
        async with pg_engine.connect() as conn:
            result = await conn.execute(text("SELECT version()"))
            version_str = result.scalar_one()
            assert "PostgreSQL" in version_str

    async def test_postgres_transaction_rollback_guarantee(self, pg_engine):
        """Verify that an explicit rollback never persists mutated data."""
        table_name = f"test_rollback_{uuid.uuid4().hex[:8]}"

        async with pg_engine.begin() as conn:
            await conn.execute(text(f"CREATE TABLE {table_name} (id serial primary key, val text)"))

        try:
            # Step 1: Open transaction, insert row, and explicitly roll back
            async_session = async_sessionmaker(pg_engine, expire_on_commit=False)
            async with async_session() as session:
                async with session.begin():
                    await session.execute(
                        text(f"INSERT INTO {table_name} (val) VALUES (:v)"),
                        {"v": "should_be_rolled_back"},
                    )
                    await session.rollback()

            # Step 2: Verify row does NOT exist
            async with pg_engine.connect() as conn:
                res = await conn.execute(text(f"SELECT count(*) FROM {table_name}"))
                count = res.scalar_one()
                assert count == 0

            # Step 3: Insert and commit
            async with async_session() as session:
                async with session.begin():
                    await session.execute(
                        text(f"INSERT INTO {table_name} (val) VALUES (:v)"),
                        {"v": "committed_value"},
                    )
                    await session.commit()

            # Step 4: Verify committed row DOES exist
            async with pg_engine.connect() as conn:
                res = await conn.execute(text(f"SELECT val FROM {table_name}"))
                val = res.scalar_one()
                assert val == "committed_value"

        finally:
            async with pg_engine.begin() as conn:
                await conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))

    async def test_postgres_concurrent_pool_connections(self, pg_engine):
        """Verify connection pool handles concurrent async queries without deadlocking."""
        async def query_pg(val: int) -> int:
            async with pg_engine.connect() as conn:
                res = await conn.execute(text("SELECT CAST(:v AS integer)"), {"v": val})
                return res.scalar_one()

        results = await asyncio.gather(*[query_pg(i) for i in range(10)])
        assert results == list(range(10))


# ==============================================================================
# 2. Redis Integration Tests: Atomic Incr, Expiration TTL, Pipelining
# ==============================================================================
@pytest.mark.skipif(not is_redis_available(), reason="Redis not available at 127.0.0.1:6379")
class TestRedisIntegration:
    """Exercises real Redis commands, TTL enforcement, and batch pipelining."""

    @pytest.fixture
    async def redis_client(self):
        client = aioredis.from_url(LIVE_REDIS_URL, decode_responses=True)
        yield client
        await client.aclose()

    async def test_redis_set_get_and_expiration(self, redis_client):
        test_key = f"test:integration:{uuid.uuid4().hex}"
        test_val = "session_token_12345"

        # Set with 2-second TTL
        await redis_client.setex(test_key, 2, test_val)
        read_val = await redis_client.get(test_key)
        assert read_val == test_val

        ttl = await redis_client.ttl(test_key)
        assert 0 < ttl <= 2

        # Clean up
        await redis_client.delete(test_key)

    async def test_redis_atomic_incr_and_rate_limiting_pattern(self, redis_client):
        counter_key = f"test:rate_limit:{uuid.uuid4().hex}"
        try:
            c1 = await redis_client.incr(counter_key)
            c2 = await redis_client.incr(counter_key)
            c3 = await redis_client.incr(counter_key)
            assert c1 == 1
            assert c2 == 2
            assert c3 == 3
        finally:
            await redis_client.delete(counter_key)

    async def test_redis_pipeline_execution(self, redis_client):
        k1 = f"test:pipe:{uuid.uuid4().hex}"
        k2 = f"test:pipe:{uuid.uuid4().hex}"
        try:
            pipe = redis_client.pipeline()
            pipe.set(k1, "v1")
            pipe.set(k2, "v2")
            pipe.get(k1)
            pipe.get(k2)
            results = await pipe.execute()
            assert results == [True, True, "v1", "v2"]
        finally:
            await redis_client.delete(k1, k2)


# ==============================================================================
# 3. Qdrant Vector Store Integration Tests: Indexing, Cosine Search, Deletion
# ==============================================================================
@pytest.mark.skipif(not is_qdrant_available(), reason="Qdrant not available at 127.0.0.1:6333")
class TestQdrantIntegration:
    """Exercises real vector indexing and filtering in Qdrant."""

    @pytest.fixture
    def settings(self):
        return Settings(
            qdrant_url=LIVE_QDRANT_URL,
            database_url=LIVE_PG_URL,
            redis_url=LIVE_REDIS_URL,
        )

    async def test_qdrant_ensure_collection_and_upsert_search(self, settings):
        client = HttpQdrantClient(settings)
        test_collection = f"test_coll_{uuid.uuid4().hex[:8]}"

        try:
            # 1. Ensure collection exists
            await client.ensure_collection(test_collection)

            project_id = uuid.uuid4()
            doc_id = uuid.uuid4()
            chunk_id = str(uuid.uuid4())

            # Generate synthetic vector
            vector = [0.1] * VECTOR_DIMENSION

            chunks = [
                {
                    "id": chunk_id,
                    "vector": vector,
                    "text": "Authentication endpoints for OAuth2 tokens",
                    "metadata": {"section": "auth"},
                }
            ]

            # 2. Upsert chunk
            await client.upsert_chunks(
                project_id=project_id,
                document_id=doc_id,
                chunks=chunks,
                collection_name=test_collection,
            )

            # 3. Search with matching vector
            results = await client.search(
                project_id=project_id,
                query_vector=vector,
                limit=5,
                collection_name=test_collection,
            )

            assert len(results) >= 1
            best_match = results[0]
            assert best_match.chunk_id == chunk_id
            assert "OAuth2" in best_match.text
            assert best_match.score > 0.99

            # 4. Search with another project_id must return 0 results (tenant isolation)
            other_results = await client.search(
                project_id=uuid.uuid4(),
                query_vector=vector,
                limit=5,
                collection_name=test_collection,
            )
            assert len(other_results) == 0

            # 5. Delete by document
            await client.delete_by_document(
                project_id=project_id,
                document_id=doc_id,
                collection_name=test_collection,
            )

            post_del_results = await client.search(
                project_id=project_id,
                query_vector=vector,
                limit=5,
                collection_name=test_collection,
            )
            assert len(post_del_results) == 0

        finally:
            # Clean up collection
            async with httpx.AsyncClient() as http:
                await http.delete(f"{LIVE_QDRANT_URL}/collections/{test_collection}")


# ==============================================================================
# 4. HashiCorp Vault Integration Tests: KV-v2 Secret Storage, Auth & Deletion
# ==============================================================================
@pytest.mark.skipif(not is_vault_available(), reason="Vault not available at 127.0.0.1:8200")
class TestVaultIntegration:
    """Exercises real Vault KV-v2 secret writing, reading, and deletion."""

    @pytest.fixture
    def vault_client(self):
        settings = Settings(
            vault_addr=LIVE_VAULT_ADDR,
            vault_token=LIVE_VAULT_TOKEN,
            database_url=LIVE_PG_URL,
            redis_url=LIVE_REDIS_URL,
        )
        return HttpVaultClient(settings)

    async def test_vault_write_read_delete_secret(self, vault_client):
        secret_path = f"test/integration/{uuid.uuid4().hex}"
        secret_data = {
            "api_key": "sk-live-test-secret-key-12345",
            "client_secret": "my-secret-credential",
        }

        # 1. Write secret
        await vault_client.write_secret(secret_path, secret_data)

        # 2. Read secret back
        retrieved = await vault_client.read_secret(secret_path)
        assert retrieved is not None
        assert retrieved.get("api_key") == "sk-live-test-secret-key-12345"
        assert retrieved.get("client_secret") == "my-secret-credential"

        # 3. Delete secret
        await vault_client.delete_secret(secret_path)

        # 4. Verify secret is gone
        deleted_data = await vault_client.read_secret(secret_path)
        assert deleted_data is None

    async def test_vault_path_traversal_rejection(self, vault_client):
        with pytest.raises(ValueError, match="Path traversal or empty path not permitted"):
            await vault_client.write_secret("../traversal_attempt", {"foo": "bar"})


# ==============================================================================
# 5. MinIO / S3 Object Storage Integration Tests: Put, Get, Delete
# ==============================================================================
@pytest.mark.skipif(not is_minio_available(), reason="MinIO not available at 127.0.0.1:9000")
class TestMinIOStorageIntegration:
    """Exercises real MinIO / S3 object storage operations."""

    @pytest.fixture
    def storage(self):
        settings = Settings(
            s3_endpoint_url=LIVE_S3_ENDPOINT,
            aws_access_key_id=LIVE_AWS_KEY,
            aws_secret_access_key=LIVE_AWS_SECRET,
            s3_bucket_uploads="apiweaver-uploads",
            s3_bucket_artifacts="apiweaver-artifacts",
            database_url=LIVE_PG_URL,
            redis_url=LIVE_REDIS_URL,
        )
        return AsyncS3ObjectStorage(settings)

    async def test_storage_put_get_delete_cycle(self, storage):
        test_key = f"integration_tests/{uuid.uuid4().hex}.txt"
        test_content = b"Integration test payload for MinIO S3 object storage."

        # Put
        await storage.put(key=test_key, content=test_content, content_type="text/plain")

        # Get
        retrieved = await storage.get(key=test_key)
        assert retrieved == test_content

        # Delete
        await storage.delete(key=test_key)

        # Confirm gone
        post_delete = await storage.get(key=test_key)
        assert post_delete is None


# ==============================================================================
# 6. Full FastAPI End-to-End Probe against Live Services (No Fakes)
# ==============================================================================
@pytest.mark.skipif(
    not (is_postgres_available() and is_redis_available()),
    reason="Both PostgreSQL and Redis must be available for full-stack API integration test",
)
class TestFullStackFastAPIIntegration:
    """Verifies FastAPI application readiness probe against live Redis and live Postgres."""

    async def test_api_readyz_against_live_postgres_and_redis(self):
        from httpx import ASGITransport, AsyncClient
        from app.main import create_app
        from app.core.deps import get_db, get_redis

        engine = create_async_engine(LIVE_PG_URL)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        real_redis = aioredis.from_url(LIVE_REDIS_URL, decode_responses=True)

        app = create_app()

        async def _override_get_db():
            async with session_factory() as session:
                yield session

        app.dependency_overrides[get_db] = _override_get_db
        app.dependency_overrides[get_redis] = lambda: real_redis

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                res = await client.get("/readyz")
                assert res.status_code == 200
                data = res.json()
                assert data["status"] == "ready"
                assert data["checks"] == {"postgres": "ok", "redis": "ok"}
        finally:
            await real_redis.aclose()
            await engine.dispose()

