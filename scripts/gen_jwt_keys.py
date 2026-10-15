#!/usr/bin/env python3
"""Generate the RS256 keypair used to sign/verify platform JWTs.

Cross-platform Python implementation replacing the bash/openssl dependency.
Generates 2048-bit RSA keys into secrets/jwt_private.pem and secrets/jwt_public.pem.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
except ImportError:
    raise SystemExit(
        "Error: 'cryptography' package is required. Install via 'pip install cryptography' or 'poetry install'."
    )


def generate_jwt_keys(secrets_dir: Path | None = None, force: bool = False) -> tuple[Path, Path]:
    """Generate RS256 private and public PEM keys if they do not exist."""
    if secrets_dir is None:
        root_dir = Path(__file__).resolve().parent.parent
        secrets_dir = root_dir / "secrets"

    secrets_dir.mkdir(parents=True, exist_ok=True)
    private_key_path = secrets_dir / "jwt_private.pem"
    public_key_path = secrets_dir / "jwt_public.pem"

    if private_key_path.exists() and public_key_path.exists() and not force:
        print(f"[jwt-keys] Existing keys found in {secrets_dir}, skipping generation.")
        return private_key_path, public_key_path

    print(f"[jwt-keys] Generating 2048-bit RS256 keypair in {secrets_dir}...")
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    private_key_path.write_bytes(private_pem)
    public_key_path.write_bytes(public_pem)

    # Restrict permissions on private key on POSIX systems
    if os.name == "posix":
        os.chmod(private_key_path, 0o600)
        os.chmod(public_key_path, 0o644)

    print(f"[jwt-keys] Successfully wrote {private_key_path}")
    print(f"[jwt-keys] Successfully wrote {public_key_path}")
    return private_key_path, public_key_path


if __name__ == "__main__":
    generate_jwt_keys()
