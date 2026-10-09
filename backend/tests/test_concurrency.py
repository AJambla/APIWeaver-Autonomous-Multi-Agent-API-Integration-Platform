"""Read-modify-write races closed with conditional updates.

Each of these used to read a row, decide in Python, and write it back, so concurrent
requests all saw the same "before" state.
"""

from __future__ import annotations

import asyncio
import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import create_access_token
from app.models.enums import OrgRole, WorkflowStatus
from app.models.workflow import WorkflowCheckpoint, WorkflowRun
from tests.conftest import TEST_PASSWORD, add_org_member, make_org, make_project, make_user


async def _register(client: AsyncClient) -> dict:
    email = f"race-{uuid.uuid4().hex[:8]}@example.com"
    res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": TEST_PASSWORD,
            "full_name": "Race",
            "organization_name": f"Race {uuid.uuid4().hex[:6]}",
        },
    )
    assert res.status_code == 201, res.text
    return {"email": email, **res.json()}


async def test_concurrent_redemptions_of_one_refresh_token_mint_one_successor(
    client: AsyncClient,
) -> None:
    account = await _register(client)
    token = account["refresh_token"]

    responses = await asyncio.gather(
        *(client.post("/api/v1/auth/refresh", json={"refresh_token": token}) for _ in range(4))
    )

    statuses = sorted(r.status_code for r in responses)
    assert statuses.count(200) <= 1, statuses
    assert statuses.count(401) >= 3, statuses


async def test_parallel_wrong_passwords_still_lock_the_account(client: AsyncClient) -> None:
    account = await _register(client)

    await asyncio.gather(
        *(
            client.post(
                "/api/v1/auth/login", json={"email": account["email"], "password": "wrong-pass-1"}
            )
            for _ in range(6)
        )
    )

    # Locked: even the correct password is refused for the lockout window.
    res = await client.post(
        "/api/v1/auth/login", json={"email": account["email"], "password": TEST_PASSWORD}
    )
    assert res.status_code == 401, res.text


async def test_an_approval_gate_can_be_answered_once(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    test_settings: Settings,
    monkeypatch,
) -> None:
    from app.api.v1 import workflows as workflows_module

    dispatched: list[uuid.UUID] = []

    async def fake_dispatch(**kwargs):
        dispatched.append(kwargs["run_id"])

    monkeypatch.setattr(workflows_module, "dispatch_run", fake_dispatch)

    async with session_factory() as session:
        owner = await make_user(session, email=f"gate-{uuid.uuid4().hex[:8]}@example.com")
        org = await make_org(session, name=f"Gate {uuid.uuid4().hex[:6]}")
        await add_org_member(session, org=org, user=owner, role=OrgRole.OWNER)
        project = await make_project(session, org=org)
        run = WorkflowRun(project_id=project.id, status=WorkflowStatus.PAUSED_FOR_APPROVAL)
        session.add(run)
        await session.flush()
        session.add(
            WorkflowCheckpoint(
                workflow_run_id=run.id,
                node_name="approval_gate",
                state_snapshot={"project_id": str(project.id), "stages": ["plan", "generate"]},
            )
        )
        await session.commit()
    token = create_access_token(
        user_id=owner.id, org_id=org.id, role=OrgRole.OWNER, settings=test_settings
    )
    headers = {"Authorization": f"Bearer {token.token}"}

    responses = await asyncio.gather(
        *(
            client.post(f"/api/v1/workflows/{run.id}/approve", json={"approved": True}, headers=headers)
            for _ in range(3)
        )
    )

    statuses = sorted(r.status_code for r in responses)
    assert statuses.count(200) == 1, statuses
    assert dispatched == [run.id]
