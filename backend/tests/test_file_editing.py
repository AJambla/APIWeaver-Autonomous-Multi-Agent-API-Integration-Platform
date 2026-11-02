"""Tests for real-time file editing endpoint (`PUT /projects/{id}/files/{file_id}/content`)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.models.codegen import CodeGenerationRun, GeneratedFile
from app.models.enums import OrgRole, ProjectRole, WorkflowStatus
from app.models.workflow import WorkflowRun
from tests.conftest import (
    TEST_PASSWORD,
    add_org_member,
    add_project_member,
    make_org,
    make_project,
    make_user,
)


@pytest.mark.asyncio
class TestFileEditingAPI:
    """Test updating generated file content via API."""

    async def _seed_generated_file(
        self, session, project_id: uuid.UUID, file_path: str, content_key: str = "s3://test/file.py"
    ) -> uuid.UUID:
        run = WorkflowRun(
            project_id=project_id,
            status=WorkflowStatus.COMPLETED,
        )
        session.add(run)
        await session.flush()

        codegen = CodeGenerationRun(
            workflow_run_id=run.id,
            target_language="python",
            status="completed",
        )
        session.add(codegen)
        await session.flush()

        gf = GeneratedFile(
            code_generation_run_id=codegen.id,
            file_path=file_path,
            content_s3_key=content_key,
            language="python" if file_path.endswith(".py") else "node",
            file_type="sdk",
            size_bytes=100,
        )
        session.add(gf)
        await session.flush()
        return gf.id

    async def test_update_file_content_success(self, client: AsyncClient, db):
        """User with Editor role can successfully update file content in S3 and DB."""
        async with db as session:
            org = await make_org(session, name=f"Edit Org {uuid.uuid4().hex[:6]}")
            editor = await make_user(session, email=f"editor-{uuid.uuid4().hex[:8]}@example.com")
            await add_org_member(session, org=org, user=editor, role=OrgRole.MEMBER)
            project = await make_project(session, org=org, name="Edit Project")
            await add_project_member(session, project=project, user=editor, role=ProjectRole.EDITOR)
            file_id = await self._seed_generated_file(session, project.id, "tools.py", "s3://bucket/tools.py")
            await session.commit()

        login = await client.post(
            "/api/v1/auth/login",
            json={"email": editor.email, "password": TEST_PASSWORD},
        )
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        fake_storage = SimpleNamespace(
            put=AsyncMock(),
            download=AsyncMock(return_value=b"print('hello')\n"),
        )
        new_valid_code = "from mcp.server.fastmcp import FastMCP\n\nmcp = FastMCP('Test')\n"

        with patch("app.services.storage_service.storage_service", fake_storage):
            res = await client.put(
                f"/api/v1/projects/{project.id}/files/{file_id}/content",
                json={"content": new_valid_code},
                headers=headers,
            )
            assert res.status_code == 200, res.text
            data = res.json()
            assert data["file_path"] == "tools.py"
            assert data["content"] == new_valid_code

            # S3 put was called with exact new bytes
            fake_storage.put.assert_awaited_once_with(
                key="s3://bucket/tools.py",
                content=new_valid_code.encode("utf-8"),
                content_type="text/plain; charset=utf-8",
            )

    async def test_update_file_rejects_invalid_python_syntax(self, client: AsyncClient, db):
        """Invalid Python syntax is rejected with 422 before saving to S3."""
        async with db as session:
            org = await make_org(session, name=f"Edit Org {uuid.uuid4().hex[:6]}")
            editor = await make_user(session, email=f"editor-{uuid.uuid4().hex[:8]}@example.com")
            await add_org_member(session, org=org, user=editor, role=OrgRole.MEMBER)
            project = await make_project(session, org=org, name="Edit Project")
            await add_project_member(session, project=project, user=editor, role=ProjectRole.EDITOR)
            file_id = await self._seed_generated_file(session, project.id, "tools.py")
            await session.commit()

        login = await client.post(
            "/api/v1/auth/login",
            json={"email": editor.email, "password": TEST_PASSWORD},
        )
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        fake_storage = SimpleNamespace(put=AsyncMock())
        broken_code = "def broken_syntax(:\n    pass\n"

        with patch("app.services.storage_service.storage_service", fake_storage):
            res = await client.put(
                f"/api/v1/projects/{project.id}/files/{file_id}/content",
                json={"content": broken_code},
                headers=headers,
            )
            assert res.status_code == 422, res.text
            fake_storage.put.assert_not_awaited()

    async def test_update_file_cross_project_isolation(self, client: AsyncClient, db):
        """Attempting to update a file belonging to another project returns 404."""
        async with db as session:
            org_a = await make_org(session, name=f"Org A {uuid.uuid4().hex[:6]}")
            user_a = await make_user(session, email=f"user-a-{uuid.uuid4().hex[:8]}@example.com")
            await add_org_member(session, org=org_a, user=user_a, role=OrgRole.OWNER)
            project_a = await make_project(session, org=org_a, name="Project A")

            org_b = await make_org(session, name=f"Org B {uuid.uuid4().hex[:6]}")
            project_b = await make_project(session, org=org_b, name="Project B")
            file_b = await self._seed_generated_file(session, project_b.id, "victim.py")
            await session.commit()

        login = await client.post(
            "/api/v1/auth/login",
            json={"email": user_a.email, "password": TEST_PASSWORD},
        )
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        fake_storage = SimpleNamespace(put=AsyncMock())
        with patch("app.services.storage_service.storage_service", fake_storage):
            res = await client.put(
                f"/api/v1/projects/{project_a.id}/files/{file_b}/content",
                json={"content": "# malicious edit"},
                headers=headers,
            )
            assert res.status_code == 404
            fake_storage.put.assert_not_awaited()
