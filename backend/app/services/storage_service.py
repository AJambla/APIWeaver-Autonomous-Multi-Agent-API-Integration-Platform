"""Object storage boundary for uploaded documents and generated artifacts.

The application persists only object keys in Postgres. This adapter keeps S3/MinIO
details out of routes and is deliberately small so tests can replace it with an
in-memory implementation.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
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

    async def ping(self) -> bool:
        try:
            async with await self._get_client() as client:
                await client.list_buckets()
                return True
        except Exception as exc:
            logger.warning("s3_ping_failed", error=str(exc))
            return False


def _is_transient_azure_error(exc: BaseException) -> bool:
    try:
        from azure.core.exceptions import AzureError, HttpResponseError
        if isinstance(exc, HttpResponseError) and exc.status_code in {408, 429, 500, 502, 503, 504}:
            return True
        if isinstance(exc, AzureError):
            return True
    except ImportError:
        pass
    return False


_azure_retry = retry(
    retry=retry_if_exception(_is_transient_azure_error),
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(multiplier=0.1, max=1.5),
    reraise=True,
)


class AsyncAzureBlobStorage:
    """Async Azure Blob Storage client using azure-storage-blob-aio."""

    def __init__(self, settings: Settings) -> None:
        self._connection_string = getattr(settings, "azure_storage_connection_string", None)
        self._account_name = getattr(settings, "azure_storage_account_name", None)
        self._account_key = getattr(settings, "azure_storage_account_key", None)
        self._artifacts_container = getattr(settings, "azure_storage_container_artifacts", "artifacts")
        self._uploads_container = getattr(settings, "azure_storage_container_uploads", "uploads")
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        from azure.storage.blob.aio import BlobServiceClient

        if self._connection_string:
            self._client = BlobServiceClient.from_connection_string(self._connection_string)
        elif self._account_name and self._account_key:
            account_url = f"https://{self._account_name}.blob.core.windows.net"
            self._client = BlobServiceClient(account_url=account_url, credential=self._account_key)
        elif self._account_name:
            from azure.identity.aio import DefaultAzureCredential
            account_url = f"https://{self._account_name}.blob.core.windows.net"
            self._client = BlobServiceClient(account_url=account_url, credential=DefaultAzureCredential())
        else:
            raise ValueError("Azure storage requires azure_storage_connection_string or azure_storage_account_name")
        return self._client

    def _target_container_for_key(self, key: str, container: str | None = None) -> str:
        if container:
            return container
        if "/documents/" in key or key.startswith(("documents/", "uploads/")):
            return self._uploads_container
        if key.startswith(("exports/", "artifacts/", "projects/", "generated/")):
            return self._artifacts_container
        return self._uploads_container

    def _fallback_container_for_key(self, target_container: str) -> str | None:
        if target_container == self._artifacts_container:
            return self._uploads_container if self._uploads_container != self._artifacts_container else None
        return self._artifacts_container if self._artifacts_container != self._uploads_container else None

    @_azure_retry
    async def get(self, *, key: str, bucket: str | None = None) -> bytes | None:
        from azure.core.exceptions import ResourceNotFoundError

        key = validate_storage_key(key)
        target_container = self._target_container_for_key(key, bucket)
        client = self._get_client()
        try:
            blob_client = client.get_blob_client(container=target_container, blob=key)
            stream = await blob_client.download_blob()
            content: bytes = await stream.readall()
            return content
        except ResourceNotFoundError:
            fallback = self._fallback_container_for_key(target_container)
            if fallback:
                try:
                    fallback_blob = client.get_blob_client(container=fallback, blob=key)
                    fallback_stream = await fallback_blob.download_blob()
                    fallback_content: bytes = await fallback_stream.readall()
                    return fallback_content
                except ResourceNotFoundError:
                    pass
                except Exception as fb_err:
                    logger.debug("azure_storage_fallback_get_failed", key=key, container=fallback, error=str(fb_err))
            return None

    @_azure_retry
    async def put(self, *, key: str, content: bytes, content_type: str | None = None, bucket: str | None = None) -> None:
        from azure.storage.blob import ContentSettings

        key = validate_storage_key(key)
        target_container = self._target_container_for_key(key, bucket)
        if not content_type:
            content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"

        client = self._get_client()
        blob_client = client.get_blob_client(container=target_container, blob=key)
        await blob_client.upload_blob(
            content,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
        )

    @_azure_retry
    async def delete(self, *, key: str, bucket: str | None = None) -> None:
        from azure.core.exceptions import ResourceNotFoundError

        key = validate_storage_key(key)
        target_container = self._target_container_for_key(key, bucket)
        client = self._get_client()
        try:
            blob_client = client.get_blob_client(container=target_container, blob=key)
            await blob_client.delete_blob()
        except ResourceNotFoundError:
            pass
        fallback = self._fallback_container_for_key(target_container)
        if fallback:
            try:
                fallback_blob = client.get_blob_client(container=fallback, blob=key)
                await fallback_blob.delete_blob()
            except ResourceNotFoundError:
                pass
            except Exception as del_err:
                logger.debug("azure_storage_fallback_delete_failed", key=key, container=fallback, error=str(del_err))

    async def upload(self, key: str, content: bytes, bucket: str | None = None) -> None:
        content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
        await self.put(key=key, content=content, content_type=content_type, bucket=bucket)

    async def download(self, key: str, bucket: str | None = None) -> bytes:
        result = await self.get(key=key, bucket=bucket)
        if result is None:
            raise FileNotFoundError(f"Object not found: {key}")
        return result

    async def ping(self) -> bool:
        try:
            client = self._get_client()
            async for _ in client.list_containers(results_per_page=1):
                break
            return True
        except Exception as exc:
            logger.warning("azure_blob_ping_failed", error=str(exc))
            return False


class LocalFileSystemObjectStorage:
    """Local filesystem storage client for development (MinIO-free)."""

    def __init__(self, settings: Settings) -> None:
        self._base_dir = Path(getattr(settings, "storage_local_dir", "./storage")).resolve()
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_path(self, key: str, bucket: str | None = None) -> Path:
        safe_key = validate_storage_key(key)
        prefix = bucket if bucket else ""
        target = (self._base_dir / prefix / safe_key).resolve()
        if not target.is_relative_to(self._base_dir):
            raise ValueError(f"Unsafe path traversal detected: {key}")
        return target

    async def get(self, *, key: str, bucket: str | None = None) -> bytes | None:
        target = self._resolve_path(key, bucket)
        if not target.is_file():
            if bucket:
                fallback = self._resolve_path(key, None)
                if fallback.is_file():
                    return fallback.read_bytes()
            return None
        return target.read_bytes()

    async def put(self, *, key: str, content: bytes, content_type: str | None = None, bucket: str | None = None) -> None:
        target = self._resolve_path(key, bucket)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    async def delete(self, *, key: str, bucket: str | None = None) -> None:
        target = self._resolve_path(key, bucket)
        if target.is_file():
            target.unlink()

    async def upload(self, key: str, content: bytes, bucket: str | None = None) -> None:
        await self.put(key=key, content=content, bucket=bucket)

    async def download(self, key: str, bucket: str | None = None) -> bytes:
        result = await self.get(key=key, bucket=bucket)
        if result is None:
            raise FileNotFoundError(f"Object not found: {key}")
        return result


def create_object_storage(settings: Settings) -> ObjectStorage:
    backend = getattr(settings, "storage_backend", "local").lower()
    if backend == "azure":
        try:
            import azure.storage.blob  # noqa: F401
            return AsyncAzureBlobStorage(settings)
        except (ImportError, ModuleNotFoundError) as err:
            logger.warning("azure_storage_not_available_fallback_to_local_storage", error=str(err))
            return LocalFileSystemObjectStorage(settings)
    elif backend == "s3":
        try:
            import aiobotocore  # noqa: F401
            return AsyncS3ObjectStorage(settings)
        except (ImportError, ModuleNotFoundError) as err:
            logger.warning("aiobotocore_not_available_fallback_to_local_storage", error=str(err))
            return LocalFileSystemObjectStorage(settings)
    return LocalFileSystemObjectStorage(settings)


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