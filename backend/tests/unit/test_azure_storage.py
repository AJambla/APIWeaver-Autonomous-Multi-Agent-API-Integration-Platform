from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from azure.core.exceptions import ResourceNotFoundError

from app.core.config import Settings
from app.services.storage_service import (
    AsyncAzureBlobStorage,
    create_object_storage,
    validate_storage_key,
)


@pytest.fixture
def mock_azure_settings() -> Settings:
    return Settings(
        storage_backend="azure",
        azure_storage_connection_string="DefaultEndpointsProtocol=https;AccountName=testacc;AccountKey=testkey;EndpointSuffix=core.windows.net",
        azure_storage_container_artifacts="artifacts",
        azure_storage_container_uploads="uploads",
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        jwt_private_key_path="secrets/jwt_private.pem",
        jwt_public_key_path="secrets/jwt_public.pem",
    )


def test_validate_storage_key() -> None:
    assert validate_storage_key("artifacts/spec.json") == "artifacts/spec.json"
    assert validate_storage_key("/documents/user1/doc.pdf") == "documents/user1/doc.pdf"
    with pytest.raises(ValueError):
        validate_storage_key("../secret.txt")
    with pytest.raises(ValueError):
        validate_storage_key("")


def test_create_object_storage_azure(mock_azure_settings: Settings) -> None:
    storage = create_object_storage(mock_azure_settings)
    assert isinstance(storage, AsyncAzureBlobStorage)


@pytest.mark.asyncio
async def test_azure_storage_put_and_get(mock_azure_settings: Settings) -> None:
    storage = AsyncAzureBlobStorage(mock_azure_settings)

    mock_blob_client = AsyncMock()
    mock_blob_client.upload_blob = AsyncMock()
    
    mock_stream = AsyncMock()
    mock_stream.readall = AsyncMock(return_value=b"hello azure blob")
    mock_blob_client.download_blob = AsyncMock(return_value=mock_stream)

    mock_client = MagicMock()
    mock_client.get_blob_client.return_value = mock_blob_client

    with patch.object(storage, "_get_client", return_value=mock_client):
        # Test put
        await storage.put(key="artifacts/test.txt", content=b"hello azure blob")
        mock_client.get_blob_client.assert_called_with(container="artifacts", blob="artifacts/test.txt")
        mock_blob_client.upload_blob.assert_called_once()

        # Test get
        content = await storage.get(key="artifacts/test.txt")
        assert content == b"hello azure blob"


@pytest.mark.asyncio
async def test_azure_storage_get_not_found(mock_azure_settings: Settings) -> None:
    storage = AsyncAzureBlobStorage(mock_azure_settings)

    mock_blob_client = AsyncMock()
    mock_blob_client.download_blob = AsyncMock(side_effect=ResourceNotFoundError("Blob not found"))

    mock_client = MagicMock()
    mock_client.get_blob_client.return_value = mock_blob_client

    with patch.object(storage, "_get_client", return_value=mock_client):
        result = await storage.get(key="artifacts/missing.txt")
        assert result is None


@pytest.mark.asyncio
async def test_azure_storage_delete(mock_azure_settings: Settings) -> None:
    storage = AsyncAzureBlobStorage(mock_azure_settings)

    mock_blob_client = AsyncMock()
    mock_blob_client.delete_blob = AsyncMock()

    mock_client = MagicMock()
    mock_client.get_blob_client.return_value = mock_blob_client

    with patch.object(storage, "_get_client", return_value=mock_client):
        await storage.delete(key="artifacts/test.txt")
        # Deletes from both primary container and fallback container
        assert mock_blob_client.delete_blob.call_count == 2
