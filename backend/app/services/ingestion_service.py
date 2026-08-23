"""Persist a validated source document and its normalized API specification."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, UnprocessableEntityError
from app.models.document import Document, DocumentVersion
from app.models.enums import DocumentFormat
from app.models.spec import APISpec, Endpoint, EndpointParameter
from app.services.spec_normalizer import NormalizedSpec, normalize
from app.services.storage_service import ObjectStorage


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
    except UnprocessableEntityError:
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
    safe_name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] or "document"
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
