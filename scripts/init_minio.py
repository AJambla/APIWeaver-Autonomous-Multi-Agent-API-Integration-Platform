#!/usr/bin/env python3
"""Initialize MinIO S3 buckets for API Weaver.

Can be run locally on bare metal:
    poetry run python scripts/init_minio.py
or in an init container.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Add root directory to sys.path so env can resolve
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

try:
    import boto3
    from botocore.client import Config
except ImportError:
    print("[init_minio] Error: boto3 is required. Install via: pip install boto3 or poetry install")
    sys.exit(1)


def init_buckets() -> None:
    endpoint_url = os.getenv("S3_ENDPOINT_URL", "http://127.0.0.1:9000")
    access_key = os.getenv("AWS_ACCESS_KEY_ID") or os.getenv("MINIO_ROOT_USER", "minioadmin")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY") or os.getenv("MINIO_ROOT_PASSWORD", "minioadmin")
    uploads_bucket = os.getenv("S3_BUCKET_UPLOADS", "apiweaver-uploads")
    artifacts_bucket = os.getenv("S3_BUCKET_ARTIFACTS", "apiweaver-artifacts")

    print(f"[init_minio] Connecting to S3/MinIO at {endpoint_url}...")
    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )

    for bucket in [uploads_bucket, artifacts_bucket]:
        try:
            s3.create_bucket(Bucket=bucket)
            print(f"[init_minio] ✔ Bucket '{bucket}' created successfully.")
        except s3.exceptions.BucketAlreadyOwnedByYou:
            print(f"[init_minio] ✔ Bucket '{bucket}' already exists (owned by you).")
        except s3.exceptions.BucketAlreadyExists:
            print(f"[init_minio] ✔ Bucket '{bucket}' already exists.")
        except Exception as exc:
            # Check if bucket is accessible
            try:
                s3.head_bucket(Bucket=bucket)
                print(f"[init_minio] ✔ Bucket '{bucket}' verified.")
            except Exception:
                print(f"[init_minio] ⚠ Bucket '{bucket}' creation note: {exc}")

    try:
        response = s3.list_buckets()
        bucket_names = [b["Name"] for b in response.get("Buckets", [])]
        print(f"[init_minio] Available buckets: {bucket_names}")
    except Exception as exc:
        print(f"[init_minio] Note listing buckets: {exc}")


if __name__ == "__main__":
    init_buckets()
