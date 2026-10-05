"""Organization scope resolution in RBAC — audit finding L2.

`require_org_permission`'s `org_id` was a bare annotation. FastAPI resolves such a
parameter from the path when the route declares `{org_id}` and from the **query string**
when it does not, so the two GitHub routes — `/github/connect` and `/github/repos`, neither
of which has an org segment — required `?org_id=` and checked the permission against
whatever the caller typed there. Since both bodies act on `principal` (the token's user and
organization) regardless, the supplied org only decided whether the gate opened: a caller
excluded from the organization they were acting in could satisfy the check by naming a
different organization they did belong to. Measured before the fix, `GET
/api/v1/github/repos?org_id=<the org they were in>` reached the route body instead of being
denied, and `POST /api/v1/github/connect` called with a valid member token answered
`400 VALIDATION_ERROR` with `{"field": "org_id", "issue": "Field required"}` — the caller had
to name an organization for a route that has no org segment to read one from.

The fix is twofold: the dependency declares `org_id` as a path parameter, and routes with no
org segment in their path gate on the principal's own organization.
"""

from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import create_access_token
from app.models.enums import OrgRole
from app.models.organization import Organization
from app.models.user import User
from app.rbac.enforce import require_org_permission
from app.rbac.policy import Permission
from tests.conftest import add_org_member, make_org, make_user


async def _user_with_two_orgs(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    home_role: str | None,
    away_role: str | None,
) -> tuple[User, Organization, Organization]:
    """A user with a `home` organization and an `away` one.

    `home` is the organization the test mints its token for; `away` is the one the caller
    tries to borrow a permission check from. A `None` role means no membership row at all.
    """
    async with session_factory() as session:
        user = await make_user(session, email=f"scope-{uuid.uuid4().hex[:10]}@example.com")
        home = await make_org(session, name=f"Home {uuid.uuid4().hex[:8]}")
        away = await make_org(session, name=f"Away {uuid.uuid4().hex[:8]}")
        if home_role is not None:
            await add_org_member(session, org=home, user=user, role=home_role)
        if away_role is not None:
            await add_org_member(session, org=away, user=user, role=away_role)
        await session.commit()
    return user, home, away


def _bearer(
    user_id: uuid.UUID,
    org_id: uuid.UUID | None,
    settings: Settings,
) -> dict[str, str]:
    """A token for `org_id`. Its `role` claim is deliberately the caller's guess: the
    membership row is re-read from the database (`deps.py`), so the roles below are set by
    `_user_with_two_orgs`, not here.
    """
    token = create_access_token(
        user_id=user_id, org_id=org_id, role=OrgRole.OWNER, settings=settings
    )
    return {"Authorization": f"Bearer {token.token}"}


# --- The invariant over the whole route table -------------------------------------------


async def test_the_org_scope_always_comes_from_a_real_path_segment(app: FastAPI) -> None:
    """One assertion over every documented parameter instead of over the two routes that
    happened to be wrong. `org_id` is the name `require_org_permission` binds, so it must
    be resolved from a segment the URL actually has — never from a query string the caller
    appends to choose which organization a check runs in.

    Both halves matter. `in: query` is the original bug. `in: path` on a path with no
    `{org_id}` segment is the shape a *future* misuse takes after the fix: the wrong route
    still documents itself correctly, so only the template comparison catches it.

    Scoped to that name deliberately: `GET /api/v1/projects?organization_id=...` also takes
    an organization from the query, and that one is a filter applied *after* the list has
    been narrowed to what the principal may see (`projects.py`), so it can only lose rows,
    never gain them.
    """
    offenders: list[str] = []
    for path, operations in app.openapi()["paths"].items():
        for method, operation in operations.items():
            for parameter in operation.get("parameters", []):
                if parameter["name"] != "org_id":
                    continue
                if parameter["in"] != "path" or "{org_id}" not in path:
                    offenders.append(f"{method.upper()} {path} (in: {parameter['in']})")
    details = "\n".join(offenders)
    assert offenders == [], f"org scope not taken from a path segment:\n{details}"


async def test_an_org_dependency_on_an_org_less_path_is_unusable_not_open(
    client: AsyncClient,
    app: FastAPI,
    session_factory: async_sessionmaker[AsyncSession],
    test_settings: Settings,
) -> None:
    """The pinning is what makes a forgotten `{org_id}` visible.

    Reusing `require_org_permission` on a route without that segment used to resolve the
    scope from the query string, silently. Declared as a path parameter the route cannot
    receive a scope at all, and nothing hints at it: no error is raised at definition or
    schema time (measured on fastapi 0.125.3 — `openapi()` simply documents the parameter as
    `in: path`). The whole signal is at request time — every call answers
    `400 VALIDATION_ERROR` `{"field": "org_id", "issue": "Field required"}`, the app's
    shaped form of FastAPI's 422, and offering the org in the query changes nothing. A route
    that does not work is a loud problem; a route that authorizes on caller-chosen input is
    not.

    The `app` fixture is rebuilt per test, so registering this deliberately broken route
    cannot leak into another one.
    """

    @app.get("/api/v1/zzz-misconfigured")
    async def misconfigured(
        _: object = Depends(require_org_permission(Permission.GITHUB_CONNECT)),
    ):
        return {"ok": "never reached"}

    user, home, _ = await _user_with_two_orgs(
        session_factory, home_role=OrgRole.OWNER, away_role=None
    )
    headers = _bearer(user.id, home.id, test_settings)

    parameters = app.openapi()["paths"]["/api/v1/zzz-misconfigured"]["get"]["parameters"]
    assert [parameter["in"] for parameter in parameters if parameter["name"] == "org_id"] == [
        "path"
    ]

    for url in (f"/api/v1/zzz-misconfigured?org_id={home.id}", "/api/v1/zzz-misconfigured"):
        response = await client.get(url, headers=headers)
        assert response.status_code == 400, response.text
        assert response.json()["error"]["details"] == [
            {"field": "org_id", "issue": "Field required"}
        ]

    anonymous = await client.get(f"/api/v1/zzz-misconfigured?org_id={home.id}")
    assert anonymous.status_code == 401, anonymous.text


# --- The bypass itself ------------------------------------------------------------------


async def test_a_foreign_org_in_the_query_does_not_open_the_gate(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    test_settings: Settings,
) -> None:
    """`/github/repos` is the org-gated route whose body works, so it shows the effect
    plainly: its 409 means "the permission check passed, you are simply not connected to
    GitHub", and that is not an answer a token from a `billing`-only organization should
    reach by naming an organization where it is a member.
    """
    user, home, away = await _user_with_two_orgs(
        session_factory, home_role=OrgRole.BILLING, away_role=OrgRole.MEMBER
    )
    headers = _bearer(user.id, home.id, test_settings)

    borrowed = await client.get(f"/api/v1/github/repos?org_id={away.id}", headers=headers)
    on_its_own = await client.get("/api/v1/github/repos", headers=headers)

    assert borrowed.status_code == on_its_own.status_code
    assert borrowed.status_code in (403, 404)


async def test_the_same_org_still_passes_the_gate(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    test_settings: Settings,
) -> None:
    """Control: pinning the scope to the token's organization must not lock out real
    members. The 409 is the route's own "no GitHub connection" answer, reached past the gate.
    """
    user, home, _ = await _user_with_two_orgs(
        session_factory, home_role=OrgRole.MEMBER, away_role=None
    )
    headers = _bearer(user.id, home.id, test_settings)

    response = await client.get("/api/v1/github/repos", headers=headers)

    assert response.status_code == 409, response.text
    assert "GitHub connection" in response.json()["error"]["message"]


async def test_a_token_without_an_organization_claim_gates_on_nothing(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    test_settings: Settings,
) -> None:
    """A `None` org claim used to leave the caller's query string as the only source of a
    scope. It authorizes nothing now.
    """
    user, _, away = await _user_with_two_orgs(
        session_factory, home_role=None, away_role=OrgRole.OWNER
    )
    headers = _bearer(user.id, None, test_settings)

    response = await client.get(f"/api/v1/github/repos?org_id={away.id}", headers=headers)

    assert response.status_code == 403


# --- Routes that do carry the segment ----------------------------------------------------


async def test_the_path_org_governs_when_the_query_disagrees(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    test_settings: Settings,
) -> None:
    """For `/org/{org_id}/api-keys`, the path is the scope and the query is inert — in both
    directions, so neither a distraction nor a substitution works.
    """
    user, home, away = await _user_with_two_orgs(
        session_factory, home_role=OrgRole.OWNER, away_role=OrgRole.OWNER
    )
    headers = _bearer(user.id, home.id, test_settings)

    mine = await client.get(f"/api/v1/org/{home.id}/api-keys?org_id={away.id}", headers=headers)
    assert mine.status_code == 200, mine.text

    stranger = uuid.uuid4()
    substitute = await client.get(
        f"/api/v1/org/{stranger}/api-keys?org_id={home.id}", headers=headers
    )
    assert substitute.status_code in (403, 404)
