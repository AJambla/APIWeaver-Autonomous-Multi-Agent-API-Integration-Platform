"""Object storage boundary for uploaded documents and generated artifacts.

The application persists only object keys in Postgres.  This adapter keeps S3/MinIO
details out of routes and is deliberately small so tests can replace it with an
in-memory implementation.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from app.core.config import Settings


class ObjectStorage(Protocol):
    async def get(self, *, key: str) -> bytes | None: ...

    async def put(self, *, key: str, content: bytes, content_type: str | None) -> None: ...

    async def delete(self, *, key: str) -> None: ...

    async def upload(self, key: str, content: bytes) -> None: ...

    async def download(self, key: str) -> bytes: ...


class S3ObjectStorage:
    """S3-compatible storage client; works with AWS S3 and MinIO."""

    def __init__(self, settings: Settings) -> None:
        # Imported here rather than at module import time so unit tests do not need AWS
        # credentials merely to construct the FastAPI application.
        import boto3

        self._bucket = settings.s3_bucket_uploads
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )

    async def get(self, *, key: str) -> bytes | None:
        import botocore.exceptions

        try:
            response = await asyncio.to_thread(
                self._client.get_object, Bucket=self._bucket, Key=key
            )
            body = await asyncio.to_thread(response["Body"].read)
            return body  # type: ignore[no-any-return]
        except botocore.exceptions.ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                return None
            raise

    async def put(self, *, key: str, content: bytes, content_type: str | None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=content,
            **extra,
        )

    async def delete(self, *, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)

    async def upload(self, key: str, content: bytes) -> None:
        await self.put(key=key, content=content, content_type="text/plain")

    async def download(self, key: str) -> bytes:
        result = await self.get(key=key)
        if result is None:
            raise FileNotFoundError(f"Object not found: {key}")
        return result


def create_object_storage(settings: Settings) -> ObjectStorage:
    return S3ObjectStorage(settings)


# Global instance for agents to use
_storage_instance: ObjectStorage | None = None


def get_storage() -> ObjectStorage:
    global _storage_instance
    if _storage_instance is None:
        from app.core.config import get_settings

        _storage_instance = create_object_storage(get_settings())
    return _storage_instance


# Backwards compatible alias
storage_service = get_storage()
