"""Tests for persist_endpoint_dependencies (Track A2).

The planner's dependency_graph (node ids + labels, edges with relationship)
must resolve to persisted Endpoint rows and land in endpoint_dependencies.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.spec import APISpec, Endpoint, EndpointDependency
from app.services.ingestion_service import persist_endpoint_dependencies
from tests.conftest import make_org, make_project

SPEC_ENDPOINTS = [
    {"method": "POST", "path": "/users"},
    {"method": "GET", "path": "/users"},
    {"method": "GET", "path": "/users/{id}"},
    {"method": "DELETE", "path": "/users/{id}"},
]


async def _setup_spec(session: AsyncSession) -> tuple[uuid.UUID, dict[tuple[str, str], uuid.UUID]]:
    org = await make_org(session, name="Dep Persist Org")
    project = await make_project(session, org=org, name="Dep Persist Project")

    spec = APISpec(project_id=project.id, raw_normalized={})
    session.add(spec)
    await session.flush()

    endpoint_ids: dict[tuple[str, str], uuid.UUID] = {}
    for ep_def in SPEC_ENDPOINTS:
        ep = Endpoint(
            api_spec_id=spec.id,
            method=ep_def["method"],
            path=ep_def["path"],
            summary="",
            response_schemas={},
            is_destructive=ep_def["method"] == "DELETE",
        )
        session.add(ep)
        await session.flush()
        endpoint_ids[(ep_def["method"], ep_def["path"])] = ep.id

    return project.id, endpoint_ids


def _plan(nodes: list[dict], edges: list[dict]) -> dict:
    return {"dependency_graph": {"nodes": nodes, "edges": edges}}


def _labeled_nodes() -> list[dict]:
    return [
        {"id": "ep_0", "label": "POST /users"},
        {"id": "ep_1", "label": "GET /users"},
        {"id": "ep_2", "label": "GET /users/{id}"},
        {"id": "ep_3", "label": "DELETE /users/{id}"},
    ]


async def test_labeled_edges_resolve_to_correct_endpoints(db: AsyncSession) -> None:
    project_id, endpoint_ids = await _setup_spec(db)

    written = await persist_endpoint_dependencies(
        db,
        project_id=project_id,
        execution_plan=_plan(
            nodes=_labeled_nodes(),
            edges=[
                {
                    "from": "ep_0",
                    "to": "ep_2",
                    "relationship": "requires_created_resource",
                }
            ],
        ),
        normalized_spec={"endpoints": SPEC_ENDPOINTS},
    )

    assert written == 1
    rows = list((await db.scalars(select(EndpointDependency))).all())
    assert len(rows) == 1
    row = rows[0]
    assert row.project_id == project_id
    assert row.from_endpoint_id == endpoint_ids[("POST", "/users")]
    assert row.to_endpoint_id == endpoint_ids[("GET", "/users/{id}")]
    assert row.relationship == "requires_created_resource"


async def test_positional_fallback_and_unknown_relationship(db: AsyncSession) -> None:
    project_id, endpoint_ids = await _setup_spec(db)

    # Nodes carry no usable label -> fall back to 0-based index into normalized_spec.
    written = await persist_endpoint_dependencies(
        db,
        project_id=project_id,
        execution_plan=_plan(
            nodes=[{"id": "ep_0", "label": ""}, {"id": "ep_1", "label": "garbage"}],
            edges=[{"from": "ep_0", "to": "ep_1", "relationship": "totally_bogus"}],
        ),
        normalized_spec={"endpoints": SPEC_ENDPOINTS},
    )

    assert written == 1
    rows = list((await db.scalars(select(EndpointDependency))).all())
    assert len(rows) == 1
    assert rows[0].from_endpoint_id == endpoint_ids[("POST", "/users")]
    assert rows[0].to_endpoint_id == endpoint_ids[("GET", "/users")]
    assert rows[0].relationship is None


async def test_rerun_replaces_existing_rows(db: AsyncSession) -> None:
    project_id, endpoint_ids = await _setup_spec(db)

    await persist_endpoint_dependencies(
        db,
        project_id=project_id,
        execution_plan=_plan(
            nodes=_labeled_nodes(),
            edges=[
                {
                    "from": "ep_0",
                    "to": "ep_1",
                    "relationship": "requires_auth",
                }
            ],
        ),
        normalized_spec={"endpoints": SPEC_ENDPOINTS},
    )

    written = await persist_endpoint_dependencies(
        db,
        project_id=project_id,
        execution_plan=_plan(
            nodes=_labeled_nodes(),
            edges=[
                {
                    "from": "ep_2",
                    "to": "ep_3",
                    "relationship": "optional_precedes",
                }
            ],
        ),
        normalized_spec={"endpoints": SPEC_ENDPOINTS},
    )

    assert written == 1
    rows = list((await db.scalars(select(EndpointDependency))).all())
    assert len(rows) == 1
    assert rows[0].from_endpoint_id == endpoint_ids[("GET", "/users/{id}")]
    assert rows[0].to_endpoint_id == endpoint_ids[("DELETE", "/users/{id}")]
    assert rows[0].relationship == "optional_precedes"


async def test_unresolvable_and_self_loop_edges_skipped(db: AsyncSession) -> None:
    project_id, _ = await _setup_spec(db)

    written = await persist_endpoint_dependencies(
        db,
        project_id=project_id,
        execution_plan=_plan(
            nodes=_labeled_nodes(),
            edges=[
                {"from": "ep_99", "to": "ep_0", "relationship": "requires_auth"},
                {"from": "ep_0", "to": "ep_0", "relationship": "requires_auth"},
                {"from": "bogus", "to": "ep_1", "relationship": "requires_auth"},
            ],
        ),
        normalized_spec={"endpoints": SPEC_ENDPOINTS},
    )

    assert written == 0
    rows = list((await db.scalars(select(EndpointDependency))).all())
    assert rows == []


async def test_no_spec_returns_zero(db: AsyncSession) -> None:
    org = await make_org(db, name="Dep No Spec Org")
    project = await make_project(db, org=org, name="Dep No Spec Project")

    written = await persist_endpoint_dependencies(
        db,
        project_id=project.id,
        execution_plan=_plan(
            nodes=_labeled_nodes(),
            edges=[{"from": "ep_0", "to": "ep_1", "relationship": "requires_auth"}],
        ),
        normalized_spec={"endpoints": SPEC_ENDPOINTS},
    )

    assert written == 0
