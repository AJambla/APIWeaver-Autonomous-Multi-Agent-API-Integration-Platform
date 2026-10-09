"""Organization rate-limit override routes and the workflow-control limiter.

Both rate-limit routes used to answer 500 on every call: they typed the RBAC dependency's
return value as `Organization` while it is the caller's `Principal`, so `org.plan_tier`
raised. The control-path limiter imported an error class that does not exist, turning a
429 into a 500 once an org exceeded its approve/cancel budget.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.ratelimit import TIER_REQUESTS_PER_MINUTE, enforce_org_rate_limit
from app.core.security import create_access_token
from app.models.enums import OrgRole
from app.models.organization import Organization
from tests.conftest import FakeRedis, add_org_member, make_org, make_user


async def _owner(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    plan_tier: str,
    role: str = OrgRole.OWNER,
) -> tuple[dict[str, str], Organization]:
    async with session_factory() as session:
        user = await make_user(session, email=f"org-{uuid.uuid4().hex[:10]}@example.com")
        org = await make_org(session, name=f"Org {uuid.uuid4().hex[:6]}", plan_tier=plan_tier)
        await add_org_member(session, org=org, user=user, role=role)
        await session.commit()
    token = create_access_token(user_id=user.id, org_id=org.id, role=role, settings=settings)
    return {"Authorization": f"Bearer {token.token}"}, org


async def test_enterprise_owner_can_set_and_remove_an_override(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    test_settings: Settings,
) -> None:
    headers, org = await _owner(session_factory, test_settings, plan_tier="enterprise")

    response = await client.put(
        f"/api/v1/organizations/{org.id}/rate-limit", json={"limit": 900}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"limit": 900, "is_override": True, "plan_tier": "enterprise"}
    async with session_factory() as session:
        assert (await session.get(Organization, org.id)).rate_limit_override == 900

    response = await client.delete(f"/api/v1/organizations/{org.id}/rate-limit", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "limit": TIER_REQUESTS_PER_MINUTE["enterprise"],
        "is_override": False,
        "plan_tier": "enterprise",
    }
    async with session_factory() as session:
        assert (await session.get(Organization, org.id)).rate_limit_override is None


async def test_non_enterprise_orgs_cannot_override(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    test_settings: Settings,
) -> None:
    headers, org = await _owner(session_factory, test_settings, plan_tier="pro")

    response = await client.put(
        f"/api/v1/organizations/{org.id}/rate-limit", json={"limit": 900}, headers=headers
    )
    assert response.status_code == 403, response.text


async def test_members_cannot_override(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    test_settings: Settings,
) -> None:
    headers, org = await _owner(
        session_factory, test_settings, plan_tier="enterprise", role=OrgRole.MEMBER
    )

    response = await client.put(
        f"/api/v1/organizations/{org.id}/rate-limit", json={"limit": 900}, headers=headers
    )
    assert response.status_code == 403, response.text


async def test_another_orgs_override_is_not_reachable(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    test_settings: Settings,
) -> None:
    headers, _ = await _owner(session_factory, test_settings, plan_tier="enterprise")
    _, other = await _owner(session_factory, test_settings, plan_tier="enterprise")

    response = await client.put(
        f"/api/v1/organizations/{other.id}/rate-limit", json={"limit": 900}, headers=headers
    )
    assert response.status_code == 404, response.text


async def test_workflow_control_limit_answers_429_not_500(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
) -> None:
    """Exhaust the approve/cancel bucket and call the limiter directly."""
    from fastapi import Response
    from starlette.requests import Request

    from app.core.errors import RateLimitExceededError
    from app.rbac.policy import Principal

    org_id = uuid.uuid4()
    principal = Principal(user_id=uuid.uuid4(), organization_id=org_id, org_role=OrgRole.OWNER)
    scope = {
        "type": "http",
        "method": "POST",
        "path": f"/api/v1/workflows/{uuid.uuid4()}/approve",
        "headers": [],
        "query_string": b"",
    }

    async with session_factory() as session:
        for _ in range(120):
            await enforce_org_rate_limit(Response(), Request(scope), principal, session, fake_redis)
        response = Response()
        try:
            await enforce_org_rate_limit(response, Request(scope), principal, session, fake_redis)
        except RateLimitExceededError as exc:
            assert exc.status_code == 429
            assert exc.headers["Retry-After"]
            assert response.headers["X-RateLimit-Remaining"] == "0"
        else:
            raise AssertionError("the 121st control request must be rate limited")
