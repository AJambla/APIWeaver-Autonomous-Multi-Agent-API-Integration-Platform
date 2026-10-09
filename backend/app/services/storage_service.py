"""Object storage boundary for uploaded documents and generated artifacts.

The application persists only object keys in Postgres. This adapter keeps S3/MinIO
details out of routes and is deliberately small so tests can replace it with an
in-memory implementation.
"""

from __future__ import annotations

import mimetypes
from typing import Any, Protocol

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.metrics import s3_download_bytes_total, s3_upload_bytes_total

logger = get_logger(__name__)


class ObjectStorage(Protocol):
    async def get(self, *, key: str) -> bytes | None: ...

    async def put(self, *, key: str, content: bytes, content_type: str | None) -> None: ...

    async def delete(self, *, key: str) -> None: ...

    async def upload(self, key: str, content: bytes) -> None: ...

    async def download(self, key: str) -> bytes: ...


def validate_storage_key(key: str) -> str:
    """Validate storage key to prevent directory traversal or malformed paths."""
    if not isinstance(key, str):
        raise ValueError("Storage key must be a string")
    cleaned = key.strip().replace("\\", "/").lstrip("/")
    parts = cleaned.split("/")
    if any(part in ("..", ".") for part in parts) or not cleaned:
        raise ValueError(f"Invalid or unsafe storage key: {key}")
    return cleaned


def _is_transient_s3_error(exc: BaseException) -> bool:
    try:
        import botocore.exceptions
        if isinstance(exc, botocore.exceptions.BotoCoreError):
            return True
        if isinstance(exc, botocore.exceptions.ClientError):
            code = exc.response.get("Error", {}).get("Code", "")
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status in {408, 429, 500, 502, 503, 504} or code in {"RequestTimeout", "SlowDown", "ServiceUnavailable"}:
                return True
    except ImportError:
        pass
    return False


_s3_retry = retry(
    retry=retry_if_exception(_is_transient_s3_error),
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(multiplier=0.1, max=1.5),
    reraise=True,
)


class AsyncS3ObjectStorage:
    """Async S3-compatible storage client using aiobotocore; works with AWS S3 and MinIO."""

    def __init__(self, settings: Settings) -> None:
        from aiobotocore.session import get_session

        self._uploads_bucket = settings.s3_bucket_uploads
        self._artifacts_bucket = settings.s3_bucket_artifacts
        self._bucket = settings.s3_bucket_uploads
        self._endpoint_url = settings.s3_endpoint_url
        self._aws_access_key_id = settings.aws_access_key_id
        self._aws_secret_access_key = settings.aws_secret_access_key
        self._session = get_session()

    def _target_bucket_for_key(self, key: str, bucket: str | None = None) -> str:
        if bucket:
            return bucket
        # Uploaded documents and specs belong in the uploads bucket
        if "/documents/" in key or key.startswith(("documents/", "uploads/")):
            return self._uploads_bucket
        # Artifacts, exports, generated SDKs and repair files belong in the dedicated artifacts bucket
        if key.startswith(("exports/", "artifacts/", "projects/", "generated/")):
            return self._artifacts_bucket
        return self._uploads_bucket

    def _fallback_bucket_for_key(self, target_bucket: str) -> str | None:
        if target_bucket == self._artifacts_bucket:
            return self._uploads_bucket if self._uploads_bucket != self._artifacts_bucket else None
        return self._artifacts_bucket if self._artifacts_bucket != self._uploads_bucket else None

    async def _get_client(self) -> Any:
        return self._session.create_client(
            "s3",
            endpoint_url=self._endpoint_url,
            aws_access_key_id=self._aws_access_key_id,
            aws_secret_access_key=self._aws_secret_access_key,
        )

    @_s3_retry
    async def get(self, *, key: str, bucket: str | None = None) -> bytes | None:
        import botocore.exceptions

        key = validate_storage_key(key)
        target_bucket = self._target_bucket_for_key(key, bucket)
        async with await self._get_client() as client:
            try:
                response = await client.get_object(Bucket=target_bucket, Key=key)
                async with response["Body"] as stream:
                    body: bytes = await stream.read()
                    return body
            except botocore.exceptions.ClientError as exc:
                if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                    fallback = self._fallback_bucket_for_key(target_bucket)
                    if fallback:
                        try:
                            fallback_res = await client.get_object(Bucket=fallback, Key=key)
                            async with fallback_res["Body"] as stream:
                                return await stream.read()
                        except botocore.exceptions.ClientError as fb_err:
                            logger.debug("storage_fallback_get_failed", key=key, bucket=fallback, error=str(fb_err))
                    return None
                raise

    @_s3_retry
    async def put(self, *, key: str, content: bytes, content_type: str | None = None, bucket: str | None = None) -> None:
        key = validate_storage_key(key)
        target_bucket = self._target_bucket_for_key(key, bucket)
        if not content_type:
            content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
        extra = {"ContentType": content_type}
        async with await self._get_client() as client:
            await client.put_object(Bucket=target_bucket, Key=key, Body=content, **extra)
        s3_upload_bytes_total.inc(len(content))

    @_s3_retry
    async def delete(self, *, key: str, bucket: str | None = None) -> None:
        key = validate_storage_key(key)
        target_bucket = self._target_bucket_for_key(key, bucket)
        async with await self._get_client() as client:
            await client.delete_object(Bucket=target_bucket, Key=key)
            fallback = self._fallback_bucket_for_key(target_bucket)
            if fallback:
                try:
                    await client.delete_object(Bucket=fallback, Key=key)
                except Exception as del_err:
                    logger.debug("storage_fallback_delete_failed", key=key, bucket=fallback, error=str(del_err))

    async def upload(self, key: str, content: bytes, bucket: str | None = None) -> None:
        content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
        await self.put(key=key, content=content, content_type=content_type, bucket=bucket)

    async def download(self, key: str, bucket: str | None = None) -> bytes:
        result = await self.get(key=key, bucket=bucket)
        if result is None:
            raise FileNotFoundError(f"Object not found: {key}")
        s3_download_bytes_total.inc(len(result))
        return result


def create_object_storage(settings: Settings) -> ObjectStorage:
    try:
        import aiobotocore  # noqa: F401
        return AsyncS3ObjectStorage(settings)
    except (ImportError, ModuleNotFoundError) as err:
        from app.core.errors import DependencyUnavailableError
        raise DependencyUnavailableError(
            "Object storage requires 'aiobotocore' library in production."
        ) from err


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

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(get_storage(), name, value)

    def __delattr__(self, name: str) -> None:
        delattr(get_storage(), name)


storage_service = _StorageServiceProxy()