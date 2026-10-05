"""Audit M3 — `audit_logs` must be append-only in the database, not only in the application.

Two halves. The guard DDL is a static string, so the first group reviews exactly what the
migration emits — including the `pg_trigger_depth()` threshold, the one number that decides
whether the guard fails open or breaks referential actions. The second group is the only way
to learn what PostgreSQL actually does with that DDL: it applies the shipped statements to a
private schema of a real server and exercises them.

Run the second group against a scratch database with:

    AUDIT_PG_TEST_URL=postgresql+asyncpg://user:pass@127.0.0.1:5432/scratch \\
        poetry run pytest tests/test_audit_immutability.py

CI supplies it for the test job's throwaway `postgres:16` service
(`.github/workflows/ci.yml`), so the guard is proven on every build. It creates nothing
outside a randomly named schema in one transaction that is never committed, so a real
server keeps nothing — but a scratch database is still the target.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import re
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

_VERSIONS = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"
_MIGRATION = _VERSIONS / "0009_audit_log_immutability.py"

PG_TEST_URL = os.environ.get("AUDIT_PG_TEST_URL", "")

_REVISION = re.compile(r'^revision: str = "(?P<rev>[^"]+)"', re.MULTILINE)
_DOWN_REVISION = re.compile(r'^down_revision: str \| None = (?P<parent>None|"[^"]+")', re.MULTILINE)


def _chain() -> dict[str, str | None]:
    """`revision -> down_revision` for every migration, read off their module literals."""
    chain: dict[str, str | None] = {}
    for path in sorted(_VERSIONS.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        revision = _REVISION.search(source)
        parent = _DOWN_REVISION.search(source)
        assert revision is not None and parent is not None, path
        value = parent.group("parent")
        chain[revision.group("rev")] = None if value == "None" else value.strip('"')
    return chain


def _emitted(operation: str, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The statements `operation` sends to the database, captured without connecting."""
    spec = importlib.util.spec_from_file_location("audit_m0009", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    emitted: list[str] = []
    monkeypatch.setattr(module.op, "execute", lambda sql, *args, **kw: emitted.append(str(sql)))
    getattr(module, operation)()
    return emitted


def test_migration_extends_the_single_head() -> None:
    chain = _chain()
    assert chain["0009"] == "0008"
    # A second migration revising 0008 would fork history and stall every later deploy.
    assert [rev for rev, parent in chain.items() if parent == "0008"] == ["0009"]
    assert [rev for rev, parent in chain.items() if parent is None] == ["0001"]


def test_guard_is_a_row_trigger_on_update_and_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    function, update_trigger, delete_trigger = _emitted("upgrade", monkeypatch)

    assert "CREATE OR REPLACE FUNCTION audit_logs_append_only()" in function
    assert "RETURNS trigger" in function

    for statement, event in ((update_trigger, "UPDATE"), (delete_trigger, "DELETE")):
        assert f"BEFORE {event} ON audit_logs" in statement
        assert "FOR EACH ROW" in statement
        assert "EXECUTE FUNCTION audit_logs_append_only()" in statement


def test_guard_exempts_only_referential_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    function = _emitted("upgrade", monkeypatch)[0]

    # PostgreSQL 16 reports a direct statement as depth 1 and an `ON DELETE CASCADE` or
    # `ON DELETE SET NULL` action as depth 2 (pinned by the PostgreSQL tests below).
    # `> 0` would exempt the application's own DELETE and fail open; `> 2` would break the
    # cascades the schema declares.
    assert "IF pg_trigger_depth() > 1 THEN" in function
    assert "RAISE EXCEPTION" in function
    assert "ERRCODE = 'insufficient_privilege'" in function


def test_guard_ddl_is_bind_parser_and_console_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Alembic wraps these strings in `text()`, and `--sql` prints them to a terminal."""
    for statement in _emitted("upgrade", monkeypatch):
        # A colon before a word character would be read as a bind parameter, and `%` as a
        # pyformat one, by any driver that uses that paramstyle.
        assert not re.search(r":\w", statement), statement
        assert "%" not in statement
        assert statement.isascii()


def test_downgrade_drops_triggers_before_the_function(monkeypatch: pytest.MonkeyPatch) -> None:
    dropped = _emitted("downgrade", monkeypatch)

    assert dropped[-1].startswith("DROP FUNCTION")
    assert sum("DROP TRIGGER" in statement for statement in dropped) == 2
    assert all("IF EXISTS" in statement for statement in dropped)


# --- against a real PostgreSQL ---------------------------------------------------------

# Own schema inside one uncommitted transaction, so a real server keeps nothing: not the
# schema, not the tables, not the function whose OID the trigger resolves at creation time.
_SETUP = (
    "CREATE SCHEMA {schema}",
    "SET LOCAL search_path = {schema}, public",
    "CREATE TABLE audit_test_organizations (id serial primary key)",
    "CREATE TABLE audit_test_users (id serial primary key)",
    """
    CREATE TABLE audit_logs (
        id serial primary key,
        organization_id integer REFERENCES audit_test_organizations (id) ON DELETE CASCADE,
        actor_user_id   integer REFERENCES audit_test_users (id)         ON DELETE SET NULL
    )
    """,
    "INSERT INTO audit_test_organizations (id) VALUES (1), (2)",
    "INSERT INTO audit_test_users (id) VALUES (1), (2)",
    # Three rows, so every statement below matches something: a guard that was never
    # reached looks exactly like a guard that passed.
    "INSERT INTO audit_logs (organization_id, actor_user_id) VALUES (1, 1), (1, 2), (2, 1)",
)


async def _prepare(conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch) -> None:
    schema = f"audit_guard_{uuid.uuid4().hex[:12]}"
    for statement in (s.format(schema=schema) for s in _SETUP):
        await conn.execute(text(statement))
    for statement in _emitted("upgrade", monkeypatch):
        await conn.execute(text(statement))


async def _count(conn: AsyncConnection, clause: str = "") -> int:
    result = await conn.execute(text(f"SELECT count(*) FROM audit_logs {clause}"))
    return int(result.scalar_one())


def _sqlstate(exc: DBAPIError) -> str:
    """PostgreSQL's SQLSTATE off the driver exception; 42501 is insufficient_privilege."""
    return str(getattr(exc.orig, "sqlstate", ""))


@pytest.mark.skipif(not PG_TEST_URL, reason="set AUDIT_PG_TEST_URL to exercise the guard")
async def test_postgres_refuses_direct_mutation_but_keeps_referential_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(PG_TEST_URL)
    try:
        async with engine.connect() as conn:
            await _prepare(conn, monkeypatch)

            with pytest.raises(DBAPIError) as update_error:
                async with conn.begin_nested():
                    await conn.execute(text("UPDATE audit_logs SET actor_user_id = 2 WHERE id = 1"))
            assert _sqlstate(update_error.value) == "42501"
            assert "append-only" in str(update_error.value.orig)

            with pytest.raises(DBAPIError) as delete_error:
                async with conn.begin_nested():
                    await conn.execute(text("DELETE FROM audit_logs WHERE id = 1"))
            assert _sqlstate(delete_error.value) == "42501"

            # A statement that matches every row must not half-apply either.
            with pytest.raises(DBAPIError):
                async with conn.begin_nested():
                    await conn.execute(text("DELETE FROM audit_logs"))

            assert await _count(conn) == 3, "blocked DML must leave every row in place"

            await conn.execute(text("DELETE FROM audit_test_organizations WHERE id = 2"))
            assert await _count(conn) == 2, "ON DELETE CASCADE must still cascade"

            await conn.execute(text("DELETE FROM audit_test_users WHERE id = 1"))
            assert await _count(conn, "WHERE actor_user_id IS NULL") == 1, (
                "ON DELETE SET NULL must still clear the actor"
            )

            await conn.execute(text("INSERT INTO audit_logs (organization_id) VALUES (1)"))
            assert await _count(conn) == 3, "INSERT is the one mutation still allowed"
    finally:
        # Nothing was committed, so the schema and everything inside it disappear.
        await engine.dispose()


@pytest.mark.skipif(not PG_TEST_URL, reason="set AUDIT_PG_TEST_URL to exercise the guard")
async def test_postgres_downgrade_makes_the_table_mutable_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(PG_TEST_URL)
    try:
        async with engine.connect() as conn:
            await _prepare(conn, monkeypatch)
            for statement in _emitted("downgrade", monkeypatch):
                await conn.execute(text(statement))

            await conn.execute(text("DELETE FROM audit_logs WHERE id = 1"))
            assert await _count(conn) == 2
    finally:
        await engine.dispose()
