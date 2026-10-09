"""Persist a validated source document and its normalized API specification."""

from __future__ import annotations

import asyncio
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
from app.models.enums import DependencyRelationship, DocumentFormat, HTTPMethod, ParameterLocation
from app.models.spec import APISpec, Endpoint, EndpointDependency, EndpointParameter
from app.services.spec_normalizer import NormalizedSpec, UnsafeDocumentError, normalize
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
        # Parsing a spec of up to max_upload_bytes is pure CPU; keep it off the event loop.
        normalized = await asyncio.to_thread(normalize, content, filename, format_hint)
    except UnsafeDocumentError:
        # Not "unstructured": unsafe to process at all, including as freeform text.
        raise
    except UnprocessableEntityError as exc:
        if format_hint is not None:
            # If a format hint was passed and failed, attempt pure content-sniffing without the hint
            try:
                normalized = await asyncio.to_thread(normalize, content, filename, None)
            except UnprocessableEntityError:
                normalized = None
        else:
            normalized = None

        if normalized is None:
            logger.warning(
                "deterministic_normalization_failed",
                filename=filename,
                format_hint=format_hint,
                error=str(exc),
            )

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
                title=_clip(normalized.title, _TITLE_MAX),
                base_url=_clip(normalized.base_url, _URL_MAX),
                raw_normalized=normalized.raw_normalized,
                confidence_score=1,
            )
            session.add(api_spec)
            await session.flush()
            await _persist_endpoints(
                session,
                api_spec.id,
                (
                    {
                        "method": e.method,
                        "path": e.path,
                        "summary": e.summary,
                        "operation_id": e.operation_id,
                        "request_schema": e.request_schema,
                        "response_schemas": e.response_schemas,
                        "parameters": e.parameters,
                        "confidence_score": 1,
                    }
                    for e in normalized.endpoints
                ),
            )
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
        title=_clip(normalized.get("title"), _TITLE_MAX),
        base_url=_clip(normalized.get("base_url"), _URL_MAX),
        raw_normalized=normalized.get("raw_normalized", normalized),
        confidence_score=_confidence(normalized.get("confidence_score"), 0.8),
    )
    session.add(api_spec)
    await session.flush()
    # LLM output: anything goes in these dicts (extra keys, lowercase or HEAD methods,
    # confidence > 1). _persist_endpoints only ever passes known, bounded columns.
    await _persist_endpoints(
        session,
        api_spec.id,
        (e for e in normalized.get("endpoints") or [] if isinstance(e, dict)),
        default_confidence=0.8,
    )
    return api_spec



# Column bounds (models/spec.py). Untrusted input longer than these used to surface as a
# 500 from the database instead of being stored.
_TITLE_MAX = 255
_URL_MAX = 1000
_PATH_MAX = 1000
_OPERATION_ID_MAX = 255
_PARAM_NAME_MAX = 255
_PARAM_TYPE_MAX = 50
_SUPPORTED_METHODS = {m.value for m in HTTPMethod}
_SUPPORTED_LOCATIONS = {loc.value for loc in ParameterLocation}


def _clip(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text[:limit] if text else None


def _confidence(value: Any, default: float) -> float:
    """A confidence in [0, 1]; the column has a CHECK and LLMs return 1.2 or null."""
    try:
        number = float(value) if value is not None else default
    except (TypeError, ValueError):
        number = default
    return min(max(number, 0.0), 1.0)


def _clean_parameters(raw: Any) -> list[dict[str, Any]]:
    """Known columns only, supported locations only, one entry per (name, location)."""
    cleaned: dict[tuple[str, str], dict[str, Any]] = {}
    for parameter in raw if isinstance(raw, list) else []:
        if not isinstance(parameter, dict) or not parameter.get("name"):
            continue
        location = str(parameter.get("location") or parameter.get("in") or "").lower()
        if location not in _SUPPORTED_LOCATIONS:
            continue
        name = str(parameter["name"])[:_PARAM_NAME_MAX]
        entry = cleaned.setdefault(
            (name, location),
            {
                "name": name,
                "location": location,
                "type": str(parameter.get("type") or "string")[:_PARAM_TYPE_MAX],
                "required": False,
            },
        )
        entry["required"] = entry["required"] or bool(parameter.get("required"))
    return list(cleaned.values())


async def _persist_endpoints(
    session: AsyncSession,
    api_spec_id: uuid.UUID,
    endpoints: Any,
    *,
    default_confidence: float = 1.0,
) -> None:
    """Insert endpoints, merging duplicates and dropping what the schema cannot hold.

    Postman collections routinely repeat a request (`GET /users` with different query
    examples). Inserting each one violated `uniq_endpoint_method_path` and failed the
    whole upload with a 500, so duplicates are merged: the first occurrence keeps its
    summary and schemas, and parameters are unioned.
    """
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for endpoint in endpoints:
        method = str(endpoint.get("method") or "").upper()
        path = str(endpoint.get("path") or "")[:_PATH_MAX]
        if method not in _SUPPORTED_METHODS or not path:
            logger.info("endpoint_skipped_unsupported", method=method, path=path[:200])
            continue
        parameters = _clean_parameters(endpoint.get("parameters"))
        existing = merged.get((method, path))
        if existing is not None:
            known = {(p["name"], p["location"]) for p in existing["parameters"]}
            existing["parameters"].extend(
                p for p in parameters if (p["name"], p["location"]) not in known
            )
            continue
        merged[(method, path)] = {
            "method": method,
            "path": path,
            "summary": endpoint.get("summary"),
            "operation_id": _clip(
                endpoint.get("operation_id") or endpoint.get("operationId"), _OPERATION_ID_MAX
            ),
            "request_schema": endpoint.get("request_schema"),
            "response_schemas": endpoint.get("response_schemas") or {},
            "confidence_score": _confidence(endpoint.get("confidence_score"), default_confidence),
            "parameters": parameters,
        }

    for entry in merged.values():
        parameters = entry.pop("parameters")
        endpoint_model = Endpoint(api_spec_id=api_spec_id, **entry)
        session.add(endpoint_model)
        await session.flush()
        session.add_all(
            EndpointParameter(endpoint_id=endpoint_model.id, **parameter) for parameter in parameters
        )
    await session.flush()


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
