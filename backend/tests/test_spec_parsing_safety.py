"""Spec parsing must not let a small upload expand into an unbounded object graph."""

from __future__ import annotations

import time

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.document import Document
from app.services.spec_normalizer import (
    MAX_ALIAS_EXPANSION_NODES,
    UnsafeDocumentError,
    _alias_expansion,
    normalize,
)
from tests.test_documents import _project_headers


def _alias_bomb(levels: int = 9) -> bytes:
    """`levels` levels of ten aliases each: about 10**levels nodes once expanded."""
    lines = ["openapi: 3.0.3", "info: {title: Bomb, version: '1'}", "paths: {}", "x-l0: &l0 [a,a,a,a,a,a,a,a,a,a]"]
    for level in range(1, levels):
        refs = ",".join([f"*l{level - 1}"] * 10)
        lines.append(f"x-l{level}: &l{level} [{refs}]")
    return ("\n".join(lines) + "\n").encode()


def test_alias_bomb_is_rejected_without_expanding_it() -> None:
    bomb = _alias_bomb()
    assert len(bomb) < 1_000

    started = time.perf_counter()
    with pytest.raises(UnsafeDocumentError, match="aliases expand"):
        normalize(bomb, "bomb.yaml")
    # The check walks distinct nodes, not the ~10**9 the aliases would expand to.
    assert time.perf_counter() - started < 2


def test_modest_anchor_reuse_is_still_accepted() -> None:
    spec = b"""openapi: 3.0.3
info: {title: Anchors, version: '1'}
paths:
  /a:
    get:
      responses: &ok
        "200": {description: OK}
  /b:
    get:
      responses: *ok
"""
    normalized = normalize(spec, "anchors.yaml")
    assert {e.path for e in normalized.endpoints} == {"/a", "/b"}


def test_self_referencing_alias_is_rejected() -> None:
    spec = b"openapi: 3.0.3\ninfo: {title: Loop, version: '1'}\npaths: {}\nx-loop: &loop [*loop]\n"
    with pytest.raises(UnsafeDocumentError, match="self-referencing"):
        normalize(spec, "loop.yaml")


def test_deeply_nested_json_is_a_422_not_a_recursion_error() -> None:
    depth = 100_000
    spec = b'{"openapi": "3.0.3", "x": ' + b"[" * depth + b"]" * depth + b"}"
    with pytest.raises(UnsafeDocumentError, match="nested too deeply"):
        normalize(spec, "deep.json")


def test_expansion_counts_only_what_aliases_add() -> None:
    shared = {"k": [1, 2, 3]}
    assert _alias_expansion({"a": {"k": [1, 2, 3]}, "b": {"k": [1, 2, 3]}}) == 0
    assert _alias_expansion({"a": shared, "b": shared}) == 5  # one extra copy: dict, list, 3 scalars
    assert _alias_expansion("scalar") == 0
    assert MAX_ALIAS_EXPANSION_NODES > 0


async def test_uploading_an_alias_bomb_is_refused_and_nothing_is_stored(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    project_id, headers = await _project_headers(client)

    res = await client.post(
        f"/api/v1/projects/{project_id}/upload",
        headers=headers,
        files={"file": ("bomb.yaml", _alias_bomb(), "application/yaml")},
    )

    assert res.status_code == 422, res.text
    async with session_factory() as session:
        assert await session.scalar(select(Document)) is None
