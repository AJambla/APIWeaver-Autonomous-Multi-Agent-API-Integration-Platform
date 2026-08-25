"""Object storage boundary for uploaded documents and generated artifacts.

The application persists only object keys in Postgres. This adapter keeps S3/MinIO
details out of routes and is deliberately small so tests can replace it with an
in-memory implementation.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.core.config import Settings


class ObjectStorage(Protocol):
    async def get(self, *, key: str) -> bytes | None: ...

    async def put(self, *, key: str, content: bytes, content_type: str | None) -> None: ...

    async def delete(self, *, key: str) -> None: ...

    async def upload(self, key: str, content: bytes) -> None: ...

    async def download(self, key: str) -> bytes: ...


class AsyncS3ObjectStorage:
    """Async S3-compatible storage client using aiobotocore; works with AWS S3 and MinIO."""

    def __init__(self, settings: Settings) -> None:
        from aiobotocore.session import get_session

        self._bucket = settings.s3_bucket_uploads
        self._endpoint_url = settings.s3_endpoint_url
        self._aws_access_key_id = settings.aws_access_key_id
        self._aws_secret_access_key = settings.aws_secret_access_key
        self._session = get_session()

    async def _get_client(self) -> Any:
        return self._session.create_client(
            "s3",
            endpoint_url=self._endpoint_url,
            aws_access_key_id=self._aws_access_key_id,
            aws_secret_access_key=self._aws_secret_access_key,
        )

    async def get(self, *, key: str) -> bytes | None:
        import botocore.exceptions

        async with await self._get_client() as client:
            try:
                response = await client.get_object(Bucket=self._bucket, Key=key)
                async with response["Body"] as stream:
                    body: bytes = await stream.read()
                    return body
            except botocore.exceptions.ClientError as exc:
                if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                    return None
                raise

    async def put(self, *, key: str, content: bytes, content_type: str | None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        async with await self._get_client() as client:
            await client.put_object(Bucket=self._bucket, Key=key, Body=content, **extra)

    async def delete(self, *, key: str) -> None:
        async with await self._get_client() as client:
            await client.delete_object(Bucket=self._bucket, Key=key)

    async def upload(self, key: str, content: bytes) -> None:
        await self.put(key=key, content=content, content_type="text/plain")

    async def download(self, key: str) -> bytes:
        result = await self.get(key=key)
        if result is None:
            raise FileNotFoundError(f"Object not found: {key}")
        return result


class InMemoryObjectStorage:
    """In-memory object storage fallback when external S3/aiobotocore is unavailable."""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    async def get(self, *, key: str) -> bytes | None:
        return self._store.get(key)

    async def put(self, *, key: str, content: bytes, content_type: str | None = None) -> None:
        self._store[key] = content

    async def delete(self, *, key: str) -> None:
        self._store.pop(key, None)

    async def upload(self, key: str, content: bytes) -> None:
        await self.put(key=key, content=content, content_type="text/plain")

    async def download(self, key: str) -> bytes:
        result = await self.get(key=key)
        if result is None:
            raise FileNotFoundError(f"Object not found: {key}")
        return result


def create_object_storage(settings: Settings) -> ObjectStorage:
    try:
        import aiobotocore  # noqa: F401
        return AsyncS3ObjectStorage(settings)
    except (ImportError, ModuleNotFoundError):
        return InMemoryObjectStorage()


# Global instance for agents to use
_storage_instance: ObjectStorage | None = None


def get_storage() -> ObjectStorage:
    global _storage_instance
    if _storage_instance is None:
        from app.core.config import get_settings

        _storage_instance = create_object_storage(get_settings())
    return _storage_instance


# Lazy proxy/getter for module-level usage
class _StorageServiceProxy:
    def __getattr__(self, name: str) -> Any:
        return getattr(get_storage(), name)


storage_service = _StorageServiceProxy()