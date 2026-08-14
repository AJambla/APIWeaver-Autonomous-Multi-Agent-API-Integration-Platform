"""Normalize supported API-document formats into the canonical API-spec shape."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import yaml

from app.core.errors import UnprocessableEntityError
from app.models.enums import DocumentFormat, HTTPMethod, ParameterLocation

_METHODS = {method.value.lower(): method.value for method in HTTPMethod}


@dataclass(frozen=True, slots=True)
class NormalizedEndpoint:
    method: str
    path: str
    summary: str | None
    request_schema: dict[str, Any] | None
    response_schemas: dict[str, Any]
    parameters: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class NormalizedSpec:
    format: str
    title: str | None
    base_url: str | None
    raw_normalized: dict[str, Any]
    endpoints: list[NormalizedEndpoint]


def detect_format(content: bytes, filename: str, format_hint: str | None) -> str:
    if format_hint:
        aliases = {"openapi": DocumentFormat.OPENAPI, "swagger": DocumentFormat.SWAGGER,
                   "postman": DocumentFormat.POSTMAN}
        if format_hint in aliases:
            return aliases[format_hint]
        raise UnprocessableEntityError("format_hint must be openapi, swagger, or postman.")

    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix == "json":
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise UnprocessableEntityError("The uploaded JSON document is invalid.") from exc
        if isinstance(parsed, dict) and "swagger" in parsed:
            return DocumentFormat.SWAGGER
        if isinstance(parsed, dict) and "openapi" in parsed:
            return DocumentFormat.OPENAPI
        if isinstance(parsed, dict) and "info" in parsed and "item" in parsed:
            return DocumentFormat.POSTMAN
    if suffix in {"yaml", "yml"}:
        try:
            parsed = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            raise UnprocessableEntityError("The uploaded YAML document is invalid.") from exc
        if isinstance(parsed, dict) and "swagger" in parsed:
            return DocumentFormat.SWAGGER
        if isinstance(parsed, dict) and "openapi" in parsed:
            return DocumentFormat.OPENAPI
    raise UnprocessableEntityError("Only OpenAPI 3.x, Swagger 2.0, and Postman v2.1 are supported.")


def normalize(content: bytes, filename: str, format_hint: str | None = None) -> NormalizedSpec:
    document_format = detect_format(content, filename, format_hint)
    try:
        data = (
            json.loads(content)
            if filename.lower().endswith(".json")
            else yaml.safe_load(content)
        )
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
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
        raise UnprocessableEntityError("Only OpenAPI 3.x documents are supported.")
    if document_format == DocumentFormat.SWAGGER and not version.startswith("2."):
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
            request_schema = _request_schema(operation, document_format)
            endpoints.append(NormalizedEndpoint(
                method=method,
                path=path,
                summary=_string_or_none(operation.get("summary") or operation.get("operationId")),
                request_schema=request_schema,
                response_schemas=_response_schemas(operation, document_format),
                parameters=parameters,
            ))

    base_url = _openapi_base_url(data, document_format)
    raw = {"format": document_format, "title": info.get("title"), "base_url": base_url,
           "endpoints": [{"method": endpoint.method, "path": endpoint.path,
                           "summary": endpoint.summary} for endpoint in endpoints]}
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
            normalized.append({"name": str(parameter.get("name", "unnamed")), "location": location,
                               "type": str(schema.get("type", parameter.get("type", "string"))),
                               "required": bool(parameter.get("required", False))})
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
    if document_format == DocumentFormat.OPENAPI:
        servers = data.get("servers")
        if isinstance(servers, list) and servers and isinstance(servers[0], dict):
            return _string_or_none(servers[0].get("url"))
        return None
    host, base_path = data.get("host"), data.get("basePath", "")
    schemes = data.get("schemes")
    scheme = schemes[0] if isinstance(schemes, list) and schemes else "https"
    return f"{scheme}://{host}{base_path}" if host else None


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
            endpoints.append(NormalizedEndpoint(method, path, _string_or_none(item.get("name")),
                                                None, {}, []))

    visit(data.get("item"))
    raw = {"format": DocumentFormat.POSTMAN, "title": info.get("name"), "base_url": None,
           "endpoints": [{"method": endpoint.method, "path": endpoint.path,
                           "summary": endpoint.summary} for endpoint in endpoints]}
    return NormalizedSpec(
        DocumentFormat.POSTMAN,
        _string_or_none(info.get("name")),
        None,
        raw,
        endpoints,
    )


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
