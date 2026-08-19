"""Test fixtures.

The suite runs against aiosqlite and a fake Redis so it needs no external services. The
two natively-partitioned tables are Postgres-only and excluded from the schema build (see
`non_partitioned_tables`); anything that must exercise real partitioning carries the
`postgres` marker.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.core.deps import get_db, get_object_storage, get_redis
from app.core.security import _load_keys, hash_password
from app.main import create_app
from app.models import Base, non_partitioned_tables
from app.models.enums import OrgRole, ProjectRole
from app.models.organization import Organization, OrganizationMember
from app.models.project import Project, ProjectMember
from app.models.user import User
from app.services.qdrant_service import FakeQdrantClient, create_qdrant_client
from app.services.vault_service import FakeVaultClient, create_vault_client

TEST_PASSWORD = "correct-horse-battery-staple"


class FakeRedis:
    """In-memory stand-in covering only what the app uses: the jti denylist and the
    rate-limit counters.

    A real Redis would make these tests require a service; the operations involved are
    simple enough that a fake is more honest than mocking at the call site.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float | None]] = {}

    def _live(self, key: str) -> str | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at is not None and expires_at <= time.time():
            del self._store[key]
            return None
        return value

    async def ping(self) -> bool:
        return True

    async def exists(self, key: str) -> int:
        return 1 if self._live(key) is not None else 0

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = (value, time.time() + ttl)

    async def incr(self, key: str) -> int:
        current = int(self._live(key) or 0) + 1
        _, expires_at = self._store.get(key, ("", None))
        self._store[key] = (str(current), expires_at)
        return current

    async def expire(self, key: str, ttl: int) -> None:
        if (value := self._live(key)) is not None:
            self._store[key] = (value, time.time() + ttl)

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self)

    async def aclose(self) -> None:
        self._store.clear()


class FakeObjectStorage:
    """In-memory S3/MinIO substitute for document-ingestion tests."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def get(self, *, key: str) -> bytes | None:
        return self.objects.get(key)

    async def put(self, *, key: str, content: bytes, content_type: str | None) -> None:
        self.objects[key] = content

    async def delete(self, *, key: str) -> None:
        self.objects.pop(key, None)


class FakePipeline:
    """Collects queued commands and runs them in order on execute()."""

    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis
        self._queued: list[tuple[str, tuple[Any, ...]]] = []

    def incr(self, key: str) -> None:
        self._queued.append(("incr", (key,)))

    def expire(self, key: str, ttl: int) -> None:
        self._queued.append(("expire", (key, ttl)))

    async def execute(self) -> list[Any]:
        results = []
        for name, args in self._queued:
            results.append(await getattr(self._redis, name)(*args))
        self._queued.clear()
        return results


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def test_settings(repo_root: Path) -> Settings:
    """Settings pointed at an in-memory database and the dev JWT keypair."""
    private_key = repo_root / "secrets" / "jwt_private.pem"
    public_key = repo_root / "secrets" / "jwt_public.pem"
    if not private_key.exists():
        pytest.skip("run scripts/gen_jwt_keys.sh to generate the dev JWT keypair")

    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379/15",
        jwt_private_key_path=private_key,
        jwt_public_key_path=public_key,
        app_env="development",
        log_level="WARNING",
    )


@pytest.fixture(autouse=True)
def _clear_caches(test_settings: Settings) -> Iterator[None]:
    """Reset the settings and keypair caches around each test.

    Both are `lru_cache`d for production, where the process reads them once. Leaving that
    cache populated across tests would let one test's settings leak into the next.
    """
    get_settings.cache_clear()
    _load_keys.cache_clear()
    yield
    get_settings.cache_clear()
    _load_keys.cache_clear()


@pytest.fixture
async def session_factory(
    test_settings: Settings,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A fresh in-memory schema per test.

    `StaticPool` with a shared in-memory URL keeps every connection on the same database;
    the default pool would hand each connection its own empty `:memory:`.
    """
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        test_settings.database_url,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    tables = non_partitioned_tables()
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=tables))

    yield async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    await engine.dispose()


@pytest.fixture
async def db(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    """A session for arranging test data directly."""
    async with session_factory() as session:
        yield session
        await session.commit()


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def fake_storage() -> FakeObjectStorage:
    return FakeObjectStorage()


@pytest.fixture
def fake_vault() -> FakeVaultClient:
    return FakeVaultClient()


@pytest.fixture
def fake_qdrant() -> FakeQdrantClient:
    return FakeQdrantClient()


@pytest.fixture
async def app(
    test_settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    fake_storage: FakeObjectStorage,
    fake_vault: FakeVaultClient,
    fake_qdrant: FakeQdrantClient,
) -> AsyncIterator[FastAPI]:
    """The real app with the database and Redis dependencies overridden.

    Everything else — middleware, exception handlers, the RBAC dependencies — is the
    production wiring, so these tests exercise the same code paths a real request takes.
    """
    get_settings.cache_clear()
    application = create_app(test_settings)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    application.dependency_overrides[get_db] = override_get_db
    application.dependency_overrides[get_redis] = lambda: fake_redis
    application.dependency_overrides[get_object_storage] = lambda: fake_storage
    application.dependency_overrides[create_vault_client] = lambda: fake_vault
    application.dependency_overrides[create_qdrant_client] = lambda: fake_qdrant
    application.dependency_overrides[get_settings] = lambda: test_settings
    # Middleware reads the client off app.state rather than through the dependency.
    application.state.redis = fake_redis

    yield application

    application.dependency_overrides.clear()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """An HTTP client speaking directly to the ASGI app.

    Note this bypasses `lifespan`, which is why `app.state.redis` is set explicitly above.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as http_client:
        yield http_client


@pytest.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    """A bearer token for a freshly registered org owner."""
    import uuid as _uuid

    from app.core.config import get_settings

    settings = get_settings()
    email = f"auth-{_uuid.uuid4().hex[:10]}@example.com"
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": TEST_PASSWORD,
            "full_name": "Auth Headers User",
            "organization_name": f"Auth Org {_uuid.uuid4().hex[:6]}",
        },
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}



async def make_user(
    session: AsyncSession, *, email: str, password: str = TEST_PASSWORD, name: str = "Test User"
) -> User:
    user = User(email=email, password_hash=hash_password(password), full_name=name)
    session.add(user)
    await session.flush()
    return user


async def make_org(
    session: AsyncSession, *, name: str, slug: str | None = None, plan_tier: str = "pro"
) -> Organization:
    org = Organization(
        name=name, slug=slug or f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}",
        plan_tier=plan_tier,
    )
    session.add(org)
    await session.flush()
    return org


async def add_org_member(
    session: AsyncSession, *, org: Organization, user: User, role: str = OrgRole.MEMBER
) -> None:
    session.add(
        OrganizationMember(organization_id=org.id, user_id=user.id, role=role)
    )
    await session.flush()


async def make_project(
    session: AsyncSession, *, org: Organization, name: str = "Test Project"
) -> Project:
    project = Project(organization_id=org.id, name=name)
    session.add(project)
    await session.flush()
    return project


async def add_project_member(
    session: AsyncSession, *, project: Project, user: User, role: str = ProjectRole.VIEWER
) -> None:
    session.add(ProjectMember(project_id=project.id, user_id=user.id, role=role))
    await session.flush()
