"""Tests for Weaver AI endpoints and path traversal protections."""

import uuid
import pytest
from httpx import AsyncClient

from app.models.spec import APISpec
from app.models.enums import OrgRole


async def _setup_project(client: AsyncClient, db) -> tuple[str, dict[str, str]]:
    email = f"weaver_{uuid.uuid4().hex[:8]}@example.com"
    res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "Password123!",
            "full_name": "Weaver Tester",
            "organization_name": "Weaver Org",
        },
    )
    assert res.status_code == 201
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    me = await client.get("/api/v1/auth/me", headers=headers)
    org_id = me.json()["organizations"][0]["organization_id"]

    proj = await client.post(
        "/api/v1/projects",
        json={"name": "Weaver Test Project", "organization_id": org_id},
        headers=headers,
    )
    assert proj.status_code == 201
    project_id = proj.json()["id"]
    return project_id, headers


@pytest.mark.asyncio
async def test_weaver_apply_rejects_path_traversal(client: AsyncClient, db) -> None:
    project_id, headers = await _setup_project(client, db)

    traversal_paths = [
        "../../etc/passwd",
        "foo/../../bar.py",
        r"windows\..\..\escaped.py",
        "../secret.txt",
    ]

    for bad_path in traversal_paths:
        res = await client.post(
            f"/api/v1/projects/{project_id}/weaver/apply",
            json={
                "file_path": bad_path,
                "content": "print('exploit')",
            },
            headers=headers,
        )
        # Must be rejected with 400 (ValidationError), never uncaught 500
        assert res.status_code == 400, f"Failed for path {bad_path}: got {res.status_code} {res.text}"
        body = res.json()
        assert "Invalid file path" in str(body) or body.get("error", {}).get("code") == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_weaver_apply_accepts_clean_path(client: AsyncClient, db) -> None:
    project_id, headers = await _setup_project(client, db)

    res = await client.post(
        f"/api/v1/projects/{project_id}/weaver/apply",
        json={
            "file_path": "src/client.py",
            "content": "def run(): pass\n",
        },
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["success"] is True
    assert res.json()["file_path"] == "src/client.py"
