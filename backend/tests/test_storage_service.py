"""Unit tests for storage service and LocalFileSystemObjectStorage."""

import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.storage_service import (
    LocalFileSystemObjectStorage,
    validate_storage_key,
)


@pytest.fixture
def temp_storage_dir():
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def local_storage(temp_storage_dir):
    settings = SimpleNamespace(storage_local_dir=temp_storage_dir)
    return LocalFileSystemObjectStorage(settings)


@pytest.mark.asyncio
async def test_put_get_delete_local_storage(local_storage):
    key = "projects/p1/exports/test.zip"
    content = b"fake-zip-binary-data"

    # Put
    await local_storage.put(key=key, content=content)

    # Get
    retrieved = await local_storage.get(key=key)
    assert retrieved == content

    # Download
    downloaded = await local_storage.download(key=key)
    assert downloaded == content

    # Delete
    await local_storage.delete(key=key)
    assert await local_storage.get(key=key) is None

    # Download after delete raises FileNotFoundError
    with pytest.raises(FileNotFoundError):
        await local_storage.download(key=key)


@pytest.mark.asyncio
async def test_put_get_with_bucket_prefix(local_storage):
    key = "manifest.json"
    content = b'{"name": "test"}'
    bucket = "apiweaver-artifacts"

    await local_storage.put(key=key, content=content, bucket=bucket)

    retrieved = await local_storage.get(key=key, bucket=bucket)
    assert retrieved == content


def test_validate_storage_key_rejects_traversal():
    with pytest.raises(ValueError, match="Invalid or unsafe storage key"):
        validate_storage_key("../secret.txt")

    with pytest.raises(ValueError, match="Invalid or unsafe storage key"):
        validate_storage_key("projects/../../etc/passwd")

    with pytest.raises(ValueError, match="Invalid or unsafe storage key"):
        validate_storage_key("")


def test_validate_storage_key_accepts_clean_paths():
    assert validate_storage_key("projects/123/export.zip") == "projects/123/export.zip"
    assert validate_storage_key("/leading/slash.txt") == "leading/slash.txt"
    assert validate_storage_key("windows\\backslashes\\path") == "windows/backslashes/path"
