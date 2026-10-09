"""Ordinary-but-messy input must be stored, not turned into a 500 by a DB constraint."""

from __future__ import annotations

import json
import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.models.audit import AuditLog
from app.models.spec import APISpec, Endpoint
from app.services.ingestion_service import persist_normalized_spec
from tests.conftest import make_org, make_project
from tests.test_documents import _project_headers


def _postman_with_repeated_request() -> bytes:
    def item(name: str, query: str) -> dict:
        return {
            "name": name,
            "request": {"method": "GET", "url": f"{{{{baseUrl}}}}/users?{query}"},
        }

    return json.dumps(
        {
            "info": {
                "name": "Users",
                "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            },
            "item": [item("List users", "page=1"), item("List users by name", "name=ada")],
        }
    ).encode()


async def test_a_postman_collection_repeating_a_request_uploads(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Duplicates violated uniq_endpoint_method_path and failed the upload with a 500."""
    project_id, headers = await _project_headers(client)

    res = await client.post(
        f"/api/v1/projects/{project_id}/upload",
        headers=headers,
        files={"file": ("users.postman.json", _postman_with_repeated_request(), "application/json")},
    )

    assert res.status_code == 202, res.text
    async with session_factory() as session:
        endpoints = list(
            await session.scalars(select(Endpoint).options(selectinload(Endpoint.parameters)))
        )
    assert [(e.method, e.path) for e in endpoints] == [("GET", "/users")]


async def test_llm_extracted_specs_with_messy_fields_are_persisted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Extra keys raised TypeError; bad methods/confidence violated CHECK constraints."""
    async with session_factory() as session:
        org = await make_org(session, name=f"Messy {uuid.uuid4().hex[:6]}")
        project = await make_project(session, org=org)
        api_spec = await persist_normalized_spec(
            session,
            project.id,
            uuid.uuid4(),
            {
                "title": "T" * 400,
                "confidence_score": None,
                "endpoints": [
                    {
                        "method": "get",
                        "path": "/users",
                        "confidence_score": 1.7,
                        "operationId": "o" * 300,
                        "parameters": [
                            {"name": "id", "in": "QUERY", "description": "extra key", "schema": {}},
                            {"name": "x", "location": "cookie"},
                        ],
                    },
                    {"method": "HEAD", "path": "/users"},
                    {"method": "GET", "path": "/users"},
                ],
            },
        )
        await session.commit()
        spec_id = api_spec.id

    async with session_factory() as session:
        stored = await session.get(APISpec, spec_id)
        endpoints = list(
            await session.scalars(
                select(Endpoint)
                .where(Endpoint.api_spec_id == spec_id)
                .options(selectinload(Endpoint.parameters))
            )
        )
    assert stored is not None and len(stored.title or "") == 255
    assert float(stored.confidence_score) == 0.8
    assert [(e.method, e.path) for e in endpoints] == [("GET", "/users")]
    assert float(endpoints[0].confidence_score) == 1.0
    assert len(endpoints[0].operation_id or "") == 255
    assert [(p.name, p.location) for p in endpoints[0].parameters] == [("id", "query")]


async def test_an_oversized_user_agent_does_not_undo_a_failed_login(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The audit insert failed on a >500-char User-Agent, rolling back the lockout count."""
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": f"nobody-{uuid.uuid4().hex[:6]}@example.com", "password": "wrong-password"},
        headers={"User-Agent": "Mozilla/5.0 " + "x" * 600},
    )

    assert res.status_code == 401, res.text
    async with session_factory() as session:
        entry = await session.scalar(select(AuditLog).order_by(AuditLog.created_at.desc()))
    assert entry is not None
    assert len(entry.user_agent or "") == 500
