"""Persist a validated source document and its normalized API specification."""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.models.document import Document, DocumentVersion
from app.models.spec import APISpec, Endpoint, EndpointParameter
from app.services.spec_normalizer import NormalizedSpec, normalize
from app.services.storage_service import ObjectStorage


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
) -> tuple[Document, APISpec, NormalizedSpec]:
    """Parse before storage, then persist the source and canonical representation."""
    normalized = normalize(content, filename, format_hint)
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
        document = Document(
            id=document_id,
            project_id=project_id,
            filename=safe_name,
            format=normalized.format,
            s3_key=object_key,
            checksum_sha256=checksum,
            uploaded_by=uploaded_by,
        )
        session.add(document)
        session.add(DocumentVersion(document_id=document_id, version_number=1))
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
    except Exception:
        await storage.delete(key=object_key)
        raise

    return document, api_spec, normalized
