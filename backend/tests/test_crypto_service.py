import os
import pytest
from pathlib import Path
from app.services.crypto_service import CryptoService, validate_secret_path


def test_validate_secret_path():
    assert validate_secret_path("org-1/project-2/api-key") == "org-1/project-2/api-key"
    assert validate_secret_path("/org-1/secrets/") == "org-1/secrets"

    with pytest.raises(ValueError):
        validate_secret_path("../../../etc/passwd")

    with pytest.raises(ValueError):
        validate_secret_path("org/../secret")

    with pytest.raises(ValueError):
        validate_secret_path("")


def test_crypto_service_encryption_roundtrip(tmp_path: Path):
    svc = CryptoService(key=b"12345678901234567890123456789012", storage_dir=tmp_path)
    payload = {"api_key": "sk-proj-12345", "client_secret": "top-secret-val"}

    ciphertext = svc.encrypt(payload)
    assert ciphertext != str(payload)
    assert isinstance(ciphertext, str)

    # Fresh nonce produces different ciphertext for same payload
    ciphertext2 = svc.encrypt(payload)
    assert ciphertext != ciphertext2

    decrypted = svc.decrypt(ciphertext)
    assert decrypted == payload

    decrypted2 = svc.decrypt(ciphertext2)
    assert decrypted2 == payload


def test_crypto_service_tamper_resistance(tmp_path: Path):
    svc = CryptoService(key=b"12345678901234567890123456789012", storage_dir=tmp_path)
    payload = {"foo": "bar"}
    token = svc.encrypt(payload)

    # Corrupting token
    import base64
    raw = bytearray(base64.urlsafe_b64decode(token))
    raw[-1] ^= 0x01
    corrupt_token = base64.urlsafe_b64encode(raw).decode("utf-8")

    with pytest.raises(Exception):
        svc.decrypt(corrupt_token)


@pytest.mark.asyncio
async def test_crypto_service_storage_roundtrip(tmp_path: Path):
    svc = CryptoService(key=b"dev-key-test", storage_dir=tmp_path)
    path = "org_123/github/token"
    data = {"access_token": "ghp_abcdef123456"}

    await svc.write_secret(path, data)
    assert await svc.read_secret(path) == data

    # Verify underlying file on disk is encrypted, not plaintext JSON
    target_file = tmp_path / "org_123" / "github" / "token"
    assert target_file.exists()
    content = target_file.read_text()
    assert "ghp_abcdef123456" not in content

    # Test deletion
    await svc.delete_secret(path)
    assert await svc.read_secret(path) is None
    assert not target_file.exists()
