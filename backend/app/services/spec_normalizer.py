"""Normalize supported API-document formats into the canonical API-spec shape."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import yaml

from app.core.errors import UnprocessableEntityError
from app.core.logging import get_logger
from app.models.enums import DocumentFormat, HTTPMethod, ParameterLocation

logger = get_logger(__name__)

_METHODS = {method.value.lower(): method.value for method in HTTPMethod}


@dataclass(frozen=True, slots=True)
class NormalizedEndpoint:
    method: str
    path: str
    summary: str | None
    request_schema: dict[str, Any] | None
    response_schemas: dict[str, Any]
    parameters: list[dict[str, Any]]
    operation_id: str | None = None
    description: str | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NormalizedSpec:
    format: str
    title: str | None
    base_url: str | None
    raw_normalized: dict[str, Any]
    endpoints: list[NormalizedEndpoint]


def _sniff_content(content: bytes, filename: str = "") -> str | None:
    """Sniff API document format directly from payload content."""
    clean = content
    if clean.startswith(b"\xef\xbb\xbf"):
        clean = clean[3:]
    parsed: Any = None
    # Try JSON first
    try:
        parsed = json.loads(clean)
    except (json.JSONDecodeError, UnicodeDecodeError):
        # Try YAML
        try:
            parsed = yaml.safe_load(clean)
        except Exception:
            parsed = None

    if isinstance(parsed, dict):
        if "swagger" in parsed:
            return DocumentFormat.SWAGGER
        if "openapi" in parsed:
            return DocumentFormat.OPENAPI
        if "info" in parsed and "item" in parsed:
            return DocumentFormat.POSTMAN

    # Suffix/filename fallback check
    lower_name = filename.lower()
    if "swagger" in lower_name:
        return DocumentFormat.SWAGGER
    if "postman" in lower_name:
        return DocumentFormat.POSTMAN

    return None


def detect_format(content: bytes, filename: str, format_hint: str | None) -> str:
    sniffed = _sniff_content(content, filename)

    if format_hint:
        aliases = {
            "openapi": DocumentFormat.OPENAPI,
            "swagger": DocumentFormat.SWAGGER,
            "postman": DocumentFormat.POSTMAN,
        }
        hint_key = format_hint.strip().lower() if format_hint else ""
        hint_format = aliases.get(hint_key)

        # If sniffed content conclusively identifies a format, check if hint contradicts it
        if sniffed is not None:
            if hint_format is not None and hint_format != sniffed:
                logger.warning(
                    "format_hint_contradicts_content_overridden",
                    format_hint=format_hint,
                    sniffed_format=sniffed,
                    filename=filename,
                )
            return sniffed

        if hint_format is not None:
            return hint_format
        raise UnprocessableEntityError("format_hint must be openapi, swagger, or postman.")

    if sniffed is not None:
        return sniffed

    raise UnprocessableEntityError("Only OpenAPI 3.x, Swagger 2.0, and Postman v2.1 are supported.")


def normalize(content: bytes, filename: str, format_hint: str | None = None) -> NormalizedSpec:
    document_format = detect_format(content, filename, format_hint)
    data: Any = None
    try:
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = yaml.safe_load(content)
    except Exception as exc:
        raise UnprocessableEntityError("The uploaded API document is invalid.") from exc
    if not isinstance(data, dict):
        raise UnprocessableEntityError("The API document must contain an object at its root.")
    if document_format == DocumentFormat.POSTMAN:
        return _normalize_postman(data)
    return _normalize_openapi(data, document_format)


def _normalize_openapi(data: dict[str, Any], document_format: str) -> NormalizedSpec:
    version_key = "openapi" if document_format == DocumentFormat.OPENAPI else "swagger"
    version = str(data.get(version_key, ""))
    if document_format == DocumentFormat.OPENAPI and not version.startswith("3."):
        # Check if the document is actually a Swagger 2.0 document mislabeled as openapi
        swagger_version = str(data.get("swagger", ""))
        if swagger_version.startswith("2."):
            document_format = DocumentFormat.SWAGGER
            version = swagger_version
        else:
            raise UnprocessableEntityError("Only OpenAPI 3.x documents are supported.")
    elif document_format == DocumentFormat.SWAGGER and not version.startswith("2."):
        # Check if the document is actually an OpenAPI 3.x document mislabeled as swagger
        openapi_version = str(data.get("openapi", ""))
        if openapi_version.startswith("3."):
            document_format = DocumentFormat.OPENAPI
            version = openapi_version
        else:
            raise UnprocessableEntityError("Only Swagger 2.0 documents are supported.")

    info = data.get("info") if isinstance(data.get("info"), dict) else {}
    endpoints: list[NormalizedEndpoint] = []
    paths = data.get("paths")
    if not isinstance(paths, dict):
        raise UnprocessableEntityError("The API document does not contain a paths object.")

    for path, path_item in paths.items():
        if not isinstance(path, str) or not isinstance(path_item, dict):
            continue
        inherited = path_item.get("parameters", [])
        for method_name, operation in path_item.items():
            method = _METHODS.get(str(method_name).lower())
            if method is None or not isinstance(operation, dict):
                continue
            parameters = _openapi_parameters(inherited, operation.get("parameters", []))
            operation_id = _string_or_none(operation.get("operationId"))
            description = _string_or_none(operation.get("description"))
            raw_tags = operation.get("tags", [])
            tags_tuple = tuple(str(t) for t in raw_tags) if isinstance(raw_tags, list) else ()
            req_schema = _request_schema(operation, document_format)
            endpoints.append(NormalizedEndpoint(
                method=method,
                path=path,
                summary=_string_or_none(operation.get("summary") or operation.get("operationId")),
                request_schema=req_schema,
                response_schemas=_response_schemas(operation, document_format),
                parameters=parameters,
                operation_id=operation_id,
                description=description,
                tags=tags_tuple,
            ))

    base_url = _openapi_base_url(data, document_format)
    definitions = data.get("definitions") if isinstance(data.get("definitions"), dict) else {}
    components = data.get("components") if isinstance(data.get("components"), dict) else {}
    sec_defs = data.get("securityDefinitions") if isinstance(data.get("securityDefinitions"), dict) else {}
    security = data.get("security") if isinstance(data.get("security"), list) else []
    tags = data.get("tags") if isinstance(data.get("tags"), list) else []

    raw = {
        "format": document_format,
        "title": _string_or_none(info.get("title")),
        "version": _string_or_none(info.get("version")),
        "description": _string_or_none(info.get("description")),
        "base_url": base_url,
        "definitions": definitions,
        "components": components,
        "securityDefinitions": sec_defs,
        "security": security,
        "tags": tags,
        "endpoints": [
            {
                "method": ep.method,
                "path": ep.path,
                "summary": ep.summary,
                "description": ep.description,
                "operation_id": ep.operation_id,
                "operationId": ep.operation_id,
                "parameters": ep.parameters,
                "request_schema": ep.request_schema,
                "response_schemas": ep.response_schemas,
                "tags": list(ep.tags),
            }
            for ep in endpoints
        ],
    }
    return NormalizedSpec(
        document_format,
        _string_or_none(info.get("title")),
        base_url,
        raw,
        endpoints,
    )


def _openapi_parameters(*groups: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, list):
            continue
        for parameter in group:
            if not isinstance(parameter, dict):
                continue
            location = parameter.get("in")
            allowed_locations = {
                item.value for item in ParameterLocation if item != ParameterLocation.BODY
            }
            if location not in allowed_locations:
                continue
            schema = parameter.get("schema") if isinstance(parameter.get("schema"), dict) else {}
            item_data: dict[str, Any] = {
                "name": str(parameter.get("name", "unnamed")),
                "location": location,
                "type": str(schema.get("type", parameter.get("type", "string"))),
                "required": bool(parameter.get("required", False)),
            }
            if "description" in parameter:
                item_data["description"] = parameter["description"]
            if schema:
                item_data["schema"] = schema
            if "default" in parameter:
                item_data["default"] = parameter["default"]
            if "enum" in parameter:
                item_data["enum"] = parameter["enum"]
            normalized.append(item_data)
    return normalized


def _request_schema(operation: dict[str, Any], document_format: str) -> dict[str, Any] | None:
    if document_format == DocumentFormat.SWAGGER:
        for parameter in operation.get("parameters", []):
            if isinstance(parameter, dict) and parameter.get("in") == "body":
                schema = parameter.get("schema")
                return schema if isinstance(schema, dict) else None
        return None
    body = operation.get("requestBody")
    if not isinstance(body, dict) or not isinstance(body.get("content"), dict):
        return None
    for media in body["content"].values():
        if isinstance(media, dict) and isinstance(media.get("schema"), dict):
            return media["schema"]
    return None


def _response_schemas(operation: dict[str, Any], document_format: str) -> dict[str, Any]:
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return {}
    normalized: dict[str, Any] = {}
    for code, response in responses.items():
        if not isinstance(response, dict):
            continue
        if document_format == DocumentFormat.SWAGGER:
            normalized[str(code)] = response.get("schema", {})
            continue
        content = response.get("content")
        if isinstance(content, dict):
            for media in content.values():
                if isinstance(media, dict) and isinstance(media.get("schema"), dict):
                    normalized[str(code)] = media["schema"]
                    break
        else:
            normalized[str(code)] = {}
    return normalized


def _openapi_base_url(data: dict[str, Any], document_format: str) -> str | None:
    servers = data.get("servers")
    if isinstance(servers, list) and servers and isinstance(servers[0], dict):
        url = _string_or_none(servers[0].get("url"))
        if url:
            return url
    host, base_path = data.get("host"), data.get("basePath", "")
    if host:
        schemes = data.get("schemes")
        scheme = schemes[0] if isinstance(schemes, list) and schemes else "https"
        return f"{scheme}://{host}{base_path}"
    return None


def _normalize_postman(data: dict[str, Any]) -> NormalizedSpec:
    info = data.get("info") if isinstance(data.get("info"), dict) else {}
    if str(info.get("schema", "")).find("collection/v2.1") == -1:
        raise UnprocessableEntityError("Only Postman Collection v2.1 is supported.")
    endpoints: list[NormalizedEndpoint] = []

    def visit(items: Any) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            if "item" in item:
                visit(item["item"])
            request = item.get("request")
            if not isinstance(request, dict):
                continue
            method = _METHODS.get(str(request.get("method", "")).lower())
            raw_url = request.get("url")
            url = raw_url.get("raw") if isinstance(raw_url, dict) else raw_url
            if method is None or not isinstance(url, str):
                continue
            parsed = urlparse(url.replace("{{baseUrl}}", ""))
            path = parsed.path or "/"
            op_id = _string_or_none(item.get("id") or item.get("name"))
            endpoints.append(NormalizedEndpoint(
                method,
                path,
                _string_or_none(item.get("name")),
                None,
                {},
                [],
                op_id,
                _string_or_none(request.get("description") if isinstance(request.get("description"), str) else None),
                (),
            ))

    visit(data.get("item"))
    raw = {
        "format": DocumentFormat.POSTMAN,
        "title": _string_or_none(info.get("name")),
        "version": _string_or_none(info.get("version")),
        "description": _string_or_none(info.get("description")),
        "base_url": None,
        "definitions": {},
        "components": {},
        "securityDefinitions": {},
        "security": [],
        "tags": [],
        "endpoints": [
            {
                "method": endpoint.method,
                "path": endpoint.path,
                "summary": endpoint.summary,
                "description": endpoint.description,
                "operation_id": endpoint.operation_id,
                "operationId": endpoint.operation_id,
                "parameters": endpoint.parameters,
                "request_schema": endpoint.request_schema,
                "response_schemas": endpoint.response_schemas,
                "tags": list(endpoint.tags),
            }
            for endpoint in endpoints
        ],
    }
    return NormalizedSpec(
        DocumentFormat.POSTMAN,
        _string_or_none(info.get("name")),
        None,
        raw,
        endpoints,
    )


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
