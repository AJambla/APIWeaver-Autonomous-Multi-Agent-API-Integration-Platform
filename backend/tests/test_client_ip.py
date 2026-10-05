"""Client address resolution — audit finding L1.

`client_ip` used to hand back the left-most `X-Forwarded-For` entry, which is free text:
the caller writes it. Two things went wrong with that. The pre-auth limiter keyed on it,
so inventing a new address per request minted a fresh budget every time and the
credential-stuffing ceiling (`Security.md §8`, A07) never applied to anyone who knew the
header existed. And the same string was written into `audit_logs.ip_address`, a Postgres
`INET` column that rejects non-addresses (measured: `invalid input syntax for type inet`,
transaction aborted, no audit row for the action that failed).

Coverage below goes from the pure function out to the real ASGI stack:

* `select_client_ip` reads the header at the depth the deployment proxies at, and returns
  either `None` or a canonical address — never caller text, never anything `INET` refuses.
* `_client_identity` gives the limiter one bucket per real client.
* Through the app, the audited address is the proxied one, and a hostile header cannot
  split or poison a bucket.
"""

from __future__ import annotations

import ipaddress

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request

from app.core.config import Settings
from app.core.deps import _as_ip, client_ip, select_client_ip
from app.core.ratelimit import ANONYMOUS_REQUESTS_PER_MINUTE, _client_identity
from app.models.audit import AuditAction, AuditLog
from tests.conftest import TEST_PASSWORD

# A peer address of the transport, i.e. what `request.client.host` is when no proxy is
# involved. Distinct from every address used in the forged headers.
PEER = "198.51.100.9"

# What the header looked like before this fix: the left-most entry, whatever the client
# typed into it.
FORGED = "1.2.3.4"


def _request(
    forwarded_for: str | None = None,
    peer: str | None = PEER,
    api_key: str | None = None,
) -> Request:
    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode()))
    if api_key is not None:
        headers.append((b"x-api-key", api_key.encode()))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/auth/login",
        "raw_path": b"/api/v1/auth/login",
        "query": "",
        "root_path": "",
        "headers": headers,
        "client": (peer, 443) if peer is not None else None,
        "server": ("testserver", 80),
    }
    return Request(scope)  # type: ignore[arg-type]


# --- The header, read at the right depth ------------------------------------------------


@pytest.mark.parametrize(
    ("forwarded_for", "hops", "expected"),
    [
        # The finding itself: one trusted proxy appended the real client after the
        # caller's own text, so the answer is the right-most entry.
        (f"{FORGED}, 203.0.113.9", 1, "203.0.113.9"),
        # Honest traffic is unchanged. A client that sends no header at all, seen through
        # one proxy, still resolves to its own address — the bucket keys of real users do
        # not move.
        ("203.0.113.9", 1, "203.0.113.9"),
        # Two proxies (ALB -> ingress): the client is two from the right, and both of the
        # entries to its left are the caller's invention.
        (f"{FORGED}, 198.51.100.1, 203.0.113.9", 2, "198.51.100.1"),
        ("203.0.113.9", 2, "203.0.113.9"),
        # Under-counting the chain names the previous proxy, not the client: conservative,
        # and still never the caller's text.
        (f"{FORGED}, 198.51.100.1, 203.0.113.9", 1, "203.0.113.9"),
        # Over-counting clamps to the left-most entry, which is client text again. Stated
        # as a limitation of the setting, not a bug in the index: keep `hops` truthful.
        ("203.0.113.9", 3, "203.0.113.9"),
        # Whitespace is exactly what proxies emit after a comma.
        (f"{FORGED} ,  203.0.113.9 ", 1, "203.0.113.9"),
        # IPv6, canonicalised the way `INET` stores it.
        ("2001:0db8:0000::0001", 1, "2001:db8::1"),
        (f"{FORGED}, 2001:db8::1", 1, "2001:db8::1"),
    ],
)
def test_forwarded_entry_is_picked_at_the_trusted_depth(
    forwarded_for: str, hops: int, expected: str
) -> None:
    assert select_client_ip(forwarded_for, PEER, hops) == expected


def test_hops_zero_ignores_the_header_entirely() -> None:
    """The fail-closed opt-out: with nothing trusted in front, only the transport counts."""
    assert select_client_ip(f"{FORGED}, 203.0.113.9", PEER, 0) == PEER
    assert select_client_ip("203.0.113.9", PEER, 0) == PEER


@pytest.mark.parametrize(
    ("forwarded_for", "expected"),
    [
        # A hop that appended something which is not an address is not reported as one.
        ("not-an-ip", PEER),
        ("203.0.113.9, lb.internal", PEER),
        ("", PEER),
        (f"{FORGED}, ", PEER),
        (f"{FORGED}, 999.999.999.999", PEER),
        # Header smuggling: only values that re-parse as an address survive, and their
        # canonical form contains no CR, LF, or comma.
        ("1.2.3.4\r\nX-Forwarded-For: 5.6.7.8", PEER),
        (f"{FORGED}, 203.0.113.9\r\nSet-Cookie: session=stolen", PEER),
    ],
)
def test_a_non_address_never_becomes_the_answer(forwarded_for: str, expected: str) -> None:
    assert select_client_ip(forwarded_for, PEER, 1) == expected


def test_missing_peer_and_missing_header_is_not_an_address() -> None:
    assert select_client_ip(None, None, 1) is None
    assert select_client_ip(None, PEER, 1) == PEER
    assert select_client_ip(None, "not-an-ip", 1) is None


def test_a_scoped_ipv6_is_not_something_the_inet_column_accepts() -> None:
    """`SELECT 'fe80::1%eth0'::inet` fails with `invalid input syntax for type inet` — run
    against the dev database. `ipaddress` accepts the scope id and returns it unchanged, so
    parsing alone would have shipped exactly the value that aborts the audited write.
    """
    assert _as_ip("fe80::1%eth0") is None
    assert _as_ip("2001:db8::1%" + "i" * 60) is None
    assert select_client_ip(f"{FORGED}, fe80::1%eth0", PEER, 1) == PEER
    assert select_client_ip(None, "fe80::1%eth0", 1) is None


@pytest.mark.parametrize(
    "value",
    [
        FORGED,
        "  203.0.113.9  ",
        "\r\n198.51.100.9",
        "2001:db8::1",
        "::ffff:203.0.113.9",
        "1.2.3.4/24",
        "1.2.3.04",
        "0x7f.1.1.1",
        "256.1.1.1",
        "1.2.3.4:8080",
        "fe80::1%eth0",
        "localhost",
        "null",
        "",
        "-",
    ],
)
def test_every_result_is_something_the_inet_column_accepts(value: str) -> None:
    """`audit_logs.ip_address` is `INET`: a value it rejects aborts the audited write."""
    result = _as_ip(value)
    if result is None:
        return
    ipaddress.ip_address(result)  # must not raise
    assert result == str(ipaddress.ip_address(result))  # canonical, so INET-stable
    for forbidden in ("\r", "\n", ",", " ", "/", "%"):
        assert forbidden not in result


# --- The limiter's bucket key ----------------------------------------------------------


@pytest.fixture
def limiter_settings(monkeypatch: pytest.MonkeyPatch, test_settings: Settings) -> Settings:
    """Middleware calls `get_settings()` directly (no DI), so pin it for these tests."""
    monkeypatch.setattr("app.core.ratelimit.get_settings", lambda: test_settings)
    return test_settings


def test_forged_left_entries_share_one_bucket(limiter_settings: Settings) -> None:
    """The bypass this fix closes: one fresh budget per invented address."""
    identities = {
        _client_identity(_request(forwarded_for=f"{forged}, 203.0.113.9"))
        for forged in ("1.2.3.4", "5.6.7.8", "9.9.9.9", "198.51.100.1")
    }
    assert identities == {"ip:203.0.113.9"}


def test_proxied_addresses_get_their_own_buckets(limiter_settings: Settings) -> None:
    identities = {
        _client_identity(_request(forwarded_for=f"{FORGED}, {client}"))
        for client in ("203.0.113.9", "203.0.113.10")
    }
    assert identities == {"ip:203.0.113.9", "ip:203.0.113.10"}


def test_a_poisoned_header_falls_back_instead_of_forking_the_bucket(
    limiter_settings: Settings,
) -> None:
    """`ip:unknown` would be its own unlimited bucket; the peer is the honest fallback."""
    assert _client_identity(_request(forwarded_for="not-an-ip")) == f"ip:{PEER}"
    assert _client_identity(_request(forwarded_for=None)) == f"ip:{PEER}"
    assert _client_identity(_request(forwarded_for=None, peer=None)) == "ip:unknown"


def test_api_key_identity_is_hashed_not_plain(limiter_settings: Settings) -> None:
    with_key = _request(forwarded_for=f"{FORGED}, 203.0.113.9", api_key="aw_live_supersecretkey")
    other_key = _request(api_key="aw_live_secondsecretkey")
    moved = _request(forwarded_for="5.6.7.8, 9.9.9.9", api_key="aw_live_supersecretkey")

    identity = _client_identity(with_key)

    assert identity.startswith("key:")
    assert "aw_live_supersecretkey" not in identity
    # A credential, not an address, decides this bucket — so the header cannot move it.
    assert _client_identity(moved) == identity
    assert _client_identity(other_key) != identity


def test_client_ip_uses_the_configured_depth(test_settings: Settings) -> None:
    assert client_ip(_request(forwarded_for=f"{FORGED}, 203.0.113.9"), test_settings) == (
        "203.0.113.9"
    )
    two_hops = test_settings.model_copy(update={"trusted_proxy_hops": 2})
    request = _request(forwarded_for=f"{FORGED}, 198.51.100.1, 203.0.113.9")
    assert client_ip(request, test_settings) == "203.0.113.9"
    assert client_ip(request, two_hops) == "198.51.100.1"


# --- Through the real application -------------------------------------------------------

REGISTRATION = {
    "email": "maya@example.com",
    "password": TEST_PASSWORD,
    "full_name": "Maya Patel",
    "organization_name": "Acme Payments",
}


async def _audited_ip(
    session_factory: async_sessionmaker[AsyncSession], action: AuditAction
) -> str | None:
    async with session_factory() as session:
        return await session.scalar(
            select(AuditLog.ip_address).where(AuditLog.action == action)
        )


async def test_register_audits_the_proxied_address_not_the_forged_one(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json=REGISTRATION,
        headers={"X-Forwarded-For": f"{FORGED}, 203.0.113.9"},
    )
    assert response.status_code == 201, response.text

    audited = await _audited_ip(session_factory, AuditAction.USER_REGISTERED)
    assert audited == "203.0.113.9"
    assert audited != FORGED


async def test_a_hostile_forwarded_header_cannot_break_the_audited_write(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Before the fix this text reached `INET` verbatim and aborted the transaction.
    (CRLF-bearing values are covered at unit level; a real client refuses to send them.)
    """
    response = await client.post(
        "/api/v1/auth/register",
        json=REGISTRATION,
        headers={"X-Forwarded-For": "not-an-ip, evil"},
    )
    assert response.status_code == 201, response.text

    audited = await _audited_ip(session_factory, AuditAction.USER_REGISTERED)
    assert audited == "127.0.0.1"  # ASGITransport's peer


async def test_forged_addresses_do_not_multiply_the_anonymous_budget(
    client: AsyncClient,
) -> None:
    """One client, four invented addresses: one counter, and it keeps counting."""
    remaining = []
    for forged in ("1.2.3.4", "5.6.7.8", "9.9.9.9", "198.51.100.1"):
        response = await client.get(
            "/api/v1/auth/me", headers={"X-Forwarded-For": f"{forged}, 203.0.113.9"}
        )
        assert int(response.headers["X-RateLimit-Limit"]) == ANONYMOUS_REQUESTS_PER_MINUTE
        remaining.append(int(response.headers["X-RateLimit-Remaining"]))

    assert remaining == sorted(remaining, reverse=True)
    assert len(set(remaining)) == len(remaining)


async def test_distinct_clients_stay_in_distinct_buckets(client: AsyncClient) -> None:
    """The fix must not merge real users: each proxied address starts at its own budget."""
    first = await client.get("/api/v1/auth/me", headers={"X-Forwarded-For": "203.0.113.9"})
    second = await client.get("/api/v1/auth/me", headers={"X-Forwarded-For": "203.0.113.10"})

    assert first.headers["X-RateLimit-Remaining"] == second.headers["X-RateLimit-Remaining"]
    assert int(first.headers["X-RateLimit-Remaining"]) == ANONYMOUS_REQUESTS_PER_MINUTE - 1


async def test_upload_audits_the_proxied_address_too(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """`documents.py` logged the transport peer directly while the auth routes used
    `client_ip`. Behind the ALB every upload was then attributed to the load balancer, so
    this site is on the same path as the finding even though its old value was never
    caller-chosen.
    """
    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    org_id = me.json()["organizations"][0]["organization_id"]
    project = await client.post(
        "/api/v1/projects",
        json={"name": "L1 upload", "organization_id": org_id},
        headers=auth_headers,
    )
    assert project.status_code == 201, project.text

    response = await client.post(
        f"/api/v1/projects/{project.json()['id']}/upload",
        headers={**auth_headers, "X-Forwarded-For": f"{FORGED}, 203.0.113.9"},
        files={"file": ("notes.txt", b"API docs: GET /items lists items", "text/plain")},
    )
    assert response.status_code == 202, response.text

    async with session_factory() as session:
        audited = await session.scalar(
            select(AuditLog.ip_address).where(AuditLog.action == "document.uploaded")
        )
    assert audited == "203.0.113.9"
