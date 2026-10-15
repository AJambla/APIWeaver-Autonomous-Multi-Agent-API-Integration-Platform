#!/usr/bin/env python3
"""Platform Bootstrap Utility for API Weaver.

Ensures zero-friction startup for local development and single-node Docker Compose:
1. Generates RS256 JWT keypair in secrets/ if missing.
2. Ensures .env exists and populates a secure random APP_ENCRYPTION_KEY (AES-256-GCM).
3. Initializes local artifact storage directories.
"""

from __future__ import annotations

import base64
import os
import secrets
import shutil
import sys
from pathlib import Path

# Add root directory to sys.path so scripts can resolve
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

try:
    from scripts.gen_jwt_keys import generate_jwt_keys
except ImportError:
    # Inline fallback if scripts package not in path
    from gen_jwt_keys import generate_jwt_keys  # type: ignore


def generate_encryption_key() -> str:
    """Generate a 32-byte URL-safe base64-encoded key for AES-256-GCM."""
    raw_key = secrets.token_bytes(32)
    return base64.urlsafe_b64encode(raw_key).decode("utf-8")


def bootstrap_environment(root_dir: Path | None = None) -> None:
    """Run full bootstrap checks and generation."""
    if root_dir is None:
        root_dir = ROOT_DIR

    print(f"[bootstrap] Initializing API Weaver environment in {root_dir}...")

    # 1. Ensure secrets directory and JWT keypair
    secrets_dir = root_dir / "secrets"
    generate_jwt_keys(secrets_dir)

    # 2. Ensure .env exists
    env_file = root_dir / ".env"
    env_example = root_dir / ".env.example"

    if not env_file.exists():
        if env_example.exists():
            print(f"[bootstrap] Creating .env from {env_example.name}...")
            shutil.copyfile(env_example, env_file)
        else:
            print("[bootstrap] Warning: .env.example not found, creating minimal .env...")
            env_file.write_text("# API Weaver Environment\n", encoding="utf-8")

    # 3. Check for APP_ENCRYPTION_KEY
    env_content = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    needs_key = True

    for line in env_content.splitlines():
        trimmed = line.strip()
        if trimmed.startswith("APP_ENCRYPTION_KEY="):
            val = trimmed.split("=", 1)[1].strip()
            if val and val != "generate_with_scripts_bootstrap":
                needs_key = False
                break

    if needs_key:
        new_key = generate_encryption_key()
        print("[bootstrap] Generating new APP_ENCRYPTION_KEY for AES-256-GCM...")
        if "APP_ENCRYPTION_KEY=" in env_content:
            # Replace placeholder line
            lines = []
            for line in env_content.splitlines():
                if line.strip().startswith("APP_ENCRYPTION_KEY="):
                    lines.append(f"APP_ENCRYPTION_KEY={new_key}")
                else:
                    lines.append(line)
            env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        else:
            # Append to file
            with env_file.open("a", encoding="utf-8") as f:
                f.write(f"\n# AES-256-GCM Master Encryption Key\nAPP_ENCRYPTION_KEY={new_key}\n")
        print("[bootstrap] Successfully wrote APP_ENCRYPTION_KEY to .env")
    else:
        print("[bootstrap] Existing valid APP_ENCRYPTION_KEY found in .env.")

    # 4. Ensure local storage directories exist
    storage_dir = root_dir / "storage"
    (storage_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (storage_dir / "uploads").mkdir(parents=True, exist_ok=True)
    print(f"[bootstrap] Local storage directories confirmed in {storage_dir}")

    print("[bootstrap] Environment bootstrap complete. Ready for startup.")


if __name__ == "__main__":
    bootstrap_environment()
