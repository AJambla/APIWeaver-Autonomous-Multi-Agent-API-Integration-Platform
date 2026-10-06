"""Persist a validated source document and its normalized API specification."""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, UnprocessableEntityError
from app.core.logging import get_logger
from app.models.document import Document, DocumentVersion
from app.models.enums import DependencyRelationship, DocumentFormat
from app.models.spec import APISpec, Endpoint, EndpointDependency, EndpointParameter
from app.services.spec_normalizer import NormalizedSpec, normalize
from app.services.storage_service import ObjectStorage

logger = get_logger(__name__)


def sanitize_filename(filename: str) -> str:
    """Sanitize uploaded document filename to prevent path traversal and injection."""
    base = Path(filename).name.strip()
    base = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", base)
    base = base.replace("..", "").strip(". ")
    if not base:
        base = "document"
    return base[:255]


def _guess_format_from_filename(filename: str) -> str:
    """Guess document format from file extension."""
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix == "pdf":
        return DocumentFormat.PDF
    if suffix in {"html", "htm"}:
        return DocumentFormat.HTML
    if suffix in {"md", "markdown"}:
        return DocumentFormat.MARKDOWN
    if suffix in {"txt", "text"}:
        return DocumentFormat.MARKDOWN  # Use MARKDOWN for text files
    return DocumentFormat.MARKDOWN


async def ingest_document(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    project_id: uuid.UUID,
    uploaded_by: uuid.UUID | None,
    filename: str,
    content: bytes,
    content_type: str | None,
    format_hint: str | None,
) -> tuple[Document, APISpec | None, NormalizedSpec | None]:
    """Parse before storage, then persist the source and canonical representation.

    For structured API specs (OpenAPI/Swagger/Postman), normalizes and creates APISpec + Endpoints.
    For freeform docs (PDF/HTML/Markdown/Text), creates Document only and returns (doc, None, None).
    """
    # Try deterministic normalization first
    try:
        normalized = normalize(content, filename, format_hint)
    except UnprocessableEntityError as exc:
        logger.warning(
            "deterministic_normalization_failed",
            filename=filename,
            format_hint=format_hint,
            error=str(exc),
        )
        # Freeform document - store Document + DocumentVersion only
        normalized = None

    checksum = hashlib.sha256(content).hexdigest()
    exists = await session.scalar(
        select(Document.id).where(
            Document.project_id == project_id,
            Document.checksum_sha256 == checksum,
        )
    )
    if exists is not None:
        raise ConflictError("This document has already been uploaded to the project.")

    document_id = uuid.uuid4()
    safe_name = sanitize_filename(filename)
    object_key = f"projects/{project_id}/documents/{document_id}/{safe_name}"
    await storage.put(key=object_key, content=content, content_type=content_type)

    try:
        document_format = normalized.format if normalized else _guess_format_from_filename(filename)
        document = Document(
            id=document_id,
            project_id=project_id,
            filename=safe_name,
            format=document_format,
            s3_key=object_key,
            checksum_sha256=checksum,
            uploaded_by=uploaded_by,
        )
        session.add(document)
        session.add(DocumentVersion(document_id=document_id, version_number=1))

        if normalized:
            # Structured spec - create APISpec and Endpoints
            api_spec = APISpec(
                project_id=project_id,
                source_document_id=document_id,
                title=normalized.title,
                base_url=normalized.base_url,
                raw_normalized=normalized.raw_normalized,
                confidence_score=1,
            )
            session.add(api_spec)
            await session.flush()
            for endpoint in normalized.endpoints:
                endpoint_model = Endpoint(
                    api_spec_id=api_spec.id,
                    method=endpoint.method,
                    path=endpoint.path,
                    summary=endpoint.summary,
                    request_schema=endpoint.request_schema,
                    response_schemas=endpoint.response_schemas,
                    confidence_score=1,
                )
                session.add(endpoint_model)
                await session.flush()
                session.add_all(
                    EndpointParameter(endpoint_id=endpoint_model.id, **parameter)
                    for parameter in endpoint.parameters
                )
            await session.flush()
            return document, api_spec, normalized
        else:
            # Freeform doc - return document only
            await session.flush()
            return document, None, None

    except Exception:
        await storage.delete(key=object_key)
        raise


async def persist_normalized_spec(
    session: AsyncSession,
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    normalized: dict[str, Any],
) -> APISpec:
    """Create APISpec + Endpoints from a pre-normalized dict (for LLM-extracted freeform specs).

    Args:
        session: Database session
        project_id: Project UUID
        document_id: Document UUID
        normalized: Normalized spec dict with title, base_url, confidence_score, endpoints, raw_normalized

    Returns:
        Created APISpec
    """
    api_spec = APISpec(
        project_id=project_id,
        source_document_id=document_id,
        title=normalized.get("title"),
        base_url=normalized.get("base_url"),
        raw_normalized=normalized.get("raw_normalized", normalized),
        confidence_score=normalized.get("confidence_score", 0.8),
    )
    session.add(api_spec)
    await session.flush()

    for endpoint in normalized.get("endpoints", []):
        endpoint_model = Endpoint(
            api_spec_id=api_spec.id,
            method=endpoint.get("method", "GET"),
            path=endpoint.get("path", "/"),
            summary=endpoint.get("summary"),
            request_schema=endpoint.get("request_schema"),
            response_schemas=endpoint.get("response_schemas", {}),
            confidence_score=endpoint.get("confidence_score", 0.8),
        )
        session.add(endpoint_model)
        await session.flush()
        for parameter in endpoint.get("parameters", []):
            session.add(EndpointParameter(endpoint_id=endpoint_model.id, **parameter))
    await session.flush()

    return api_spec


async def persist_endpoint_dependencies(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    execution_plan: dict[str, Any],
    normalized_spec: dict[str, Any],
) -> int:
    """Write the planner's dependency_graph into EndpointDependency rows.

    Planner node ids resolve to persisted Endpoint rows by matching the node label
    ("METHOD path") against the spec endpoints; the 0-based positional index into
    normalized_spec["endpoints"] is the fallback when a label is missing or
    unparseable. Rows are replaced per project so re-plans stay idempotent.
    Returns the number of edges written.
    """
    graph = execution_plan.get("dependency_graph") or {}
    edges = graph.get("edges") or []
    if not edges:
        return 0

    spec_endpoints = normalized_spec.get("endpoints", [])

    node_keys: dict[str, tuple[str, str]] = {}
    for node in graph.get("nodes") or []:
        label = str(node.get("label", ""))
        parts = label.split(" ", 1)
        if len(parts) == 2 and parts[0]:
            node_keys[str(node.get("id", ""))] = (parts[0].upper(), parts[1])

    def _resolve_key(node_id: str) -> tuple[str, str] | None:
        if node_id in node_keys:
            return node_keys[node_id]
        suffix = node_id.removeprefix("ep_")
        try:
            idx = int(suffix)
        except ValueError:
            return None
        if 0 <= idx < len(spec_endpoints):
            ep = spec_endpoints[idx]
            return (str(ep.get("method", "GET")).upper(), str(ep.get("path", "/")))
        return None

    latest_spec = await session.scalar(
        select(APISpec)
        .where(APISpec.project_id == project_id)
        .order_by(APISpec.created_at.desc())
        .limit(1)
    )
    if latest_spec is None:
        logger.warning("dependency_persist_no_spec", project_id=str(project_id))
        return 0

    db_endpoints = list(
        (await session.scalars(select(Endpoint).where(Endpoint.api_spec_id == latest_spec.id))).all()
    )
    endpoint_ids: dict[tuple[str, str], uuid.UUID] = {}
    for ep in db_endpoints:
        endpoint_ids.setdefault((ep.method.upper(), ep.path), ep.id)

    resolved: dict[str, uuid.UUID] = {}

    def _resolve_endpoint(node_id: str) -> uuid.UUID | None:
        if node_id in resolved:
            return resolved[node_id]
        key = _resolve_key(node_id)
        endpoint_id = endpoint_ids.get(key) if key is not None else None
        resolved[node_id] = endpoint_id  # type: ignore[assignment]
        return endpoint_id

    await session.execute(
        delete(EndpointDependency).where(EndpointDependency.project_id == project_id)
    )

    valid_relationships = {r.value for r in DependencyRelationship}
    written = 0
    for edge in edges:
        from_id = _resolve_endpoint(str(edge.get("from", "")))
        to_id = _resolve_endpoint(str(edge.get("to", "")))
        if from_id is None or to_id is None or from_id == to_id:
            logger.warning(
                "dependency_edge_skipped",
                project_id=str(project_id),
                from_node=str(edge.get("from", "")),
                to_node=str(edge.get("to", "")),
            )
            continue
        relationship = edge.get("relationship")
        if relationship not in valid_relationships:
            relationship = None
        session.add(
            EndpointDependency(
                project_id=project_id,
                from_endpoint_id=from_id,
                to_endpoint_id=to_id,
                relationship=relationship,
            )
        )
        written += 1
    await session.flush()
    return written
