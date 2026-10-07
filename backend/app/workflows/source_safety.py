"""Source-safe shaping for spec values that end up inside generated code (`audit M6`).

Every field of a normalized spec comes from an uploaded document or a fetched API, and
the code generators paste those fields straight into Python and TypeScript source —
identifier positions, string literals, docstrings and comments. A value holding a quote,
a newline or a `*/` therefore changes the meaning of the generated file instead of just
its text, so each kind of slot gets its own allow-list rather than one shared escaper.
"""

from __future__ import annotations

import json
import re
from keyword import iskeyword
from typing import Any

HTTP_METHODS = frozenset(
    {"get", "put", "post", "patch", "delete", "options", "head", "trace"}
)

DEFAULT_BASE_URL = "https://api.example.com"

# Quotes and backslashes end a literal, backticks and angle brackets end a template
# string, and an asterisk would let a value close a block comment.
_UNSAFE_TEXT = re.compile(r"[\"'`\\<>*]")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")
_UNSAFE_IDENT = re.compile(r"[^A-Za-z0-9_]")
_UNSAFE_TYPE = re.compile(r"[^A-Za-z0-9_]")
# Titles reach identifier positions after the templates strip spaces and hyphens.
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9 _-]")
_UNSAFE_PATH = re.compile(r"[^A-Za-z0-9/{}._~+-]")
_UNSAFE_URL = re.compile(r"[^A-Za-z0-9:/._~?&=%+#-]")


def _as_str(value: Any) -> str:
    return "" if value is None else str(value)


def to_text(value: Any, *, fallback: str = "", limit: int = 200) -> str:
    """Collapse to one line of prose that cannot end a string, comment or docstring."""
    text = _WHITESPACE.sub(" ", _CONTROL.sub(" ", _UNSAFE_TEXT.sub("", _as_str(value)))).strip()
    return text[:limit] or fallback


def to_identifier(value: Any, *, fallback: str, limit: int = 60) -> str:
    """Shape a value into a usable Python/TypeScript identifier."""
    name = _UNSAFE_IDENT.sub("_", _as_str(value).strip())[:limit].rstrip("_")
    if not name or not (name[0].isalpha() or name[0] == "_") or iskeyword(name):
        return f"{fallback}_{name}"[:limit] if name else fallback
    return name


def to_display_name(value: Any, *, fallback: str = "API Client", limit: int = 60) -> str:
    """Shape a spec title, which is used as both prose and an identifier stem."""
    name = _WHITESPACE.sub(" ", _UNSAFE_NAME.sub("", _as_str(value))).strip()
    return name[:limit] or fallback


def to_base_url(value: Any) -> str:
    """Keep only URLs: the value is pasted into a quoted default inside generated code."""
    url = _UNSAFE_URL.sub("", _as_str(value)).strip()
    if not url.startswith(("http://", "https://")):
        return DEFAULT_BASE_URL
    return url


def to_path(value: Any, *, limit: int = 300) -> str:
    """Shape a URL path, keeping `{param}` placeholders but nothing quotable."""
    path = _UNSAFE_PATH.sub("", _as_str(value)).strip()
    if not path.startswith("/"):
        path = "/" + path
    return path[:limit] or "/"


def to_http_method(value: Any) -> str:
    """Lowercase HTTP verb, or `get`: the verb is used as an attribute name."""
    method = _as_str(value).strip().lower()
    return method if method in HTTP_METHODS else "get"


def to_type_name(value: Any, *, fallback: str = "string") -> str:
    """Annotation token; the templates compare against `string` before using it raw."""
    name = _UNSAFE_TYPE.sub("", _as_str(value))[:30]
    return name or fallback


# Spec type names come from the uploaded document, but a JSON Schema type is not a
# TypeScript type: `integer`, `array` and `object` are not valid annotations in that
# language. `unknown[]` and `Record<string, unknown>` stay open because a normalized
# parameter carries no item or property types to widen them with.
_TS_TYPES = {
    "string": "string",
    "integer": "number",
    "number": "number",
    "boolean": "boolean",
    "array": "unknown[]",
    "object": "Record<string, unknown>",
    "null": "null",
}


def to_ts_type(value: Any) -> str:
    """Translate a spec type name into a TypeScript type expression."""
    return _TS_TYPES.get(_as_str(value).strip().lower(), "unknown")


# Spec type names mapped to standard Python types.
_PY_TYPES = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "array": "list[Any]",
    "object": "dict[str, Any]",
    "null": "None",
}


def to_py_type(value: Any) -> str:
    """Translate a spec type name into a Python type expression."""
    return _PY_TYPES.get(_as_str(value).strip().lower(), "Any")


def to_literal(value: Any) -> str:
    """A complete string literal (`json.dumps` output is a valid Python and JS literal)."""
    return json.dumps(str(value))


def derived_operation_id(method: str, path: str) -> str:
    """Operation name for a spec endpoint that declares no operationId."""
    return f"{method}_{to_path(path).replace('/', '_').replace('{', '').replace('}', '')}"


def safe_parameter(param: dict[str, Any]) -> dict[str, Any]:
    """Parameter whose fields are safe for argument names and annotations."""
    loc = to_identifier(param.get("location"), fallback="query")
    req = bool(param.get("required")) or (loc == "path")
    return {
        **param,
        "name": to_identifier(param.get("name"), fallback="param"),
        "type": to_type_name(param.get("type")),
        "location": loc,
        "required": req,
    }


def safe_endpoint(endpoint: dict[str, Any]) -> dict[str, Any]:
    """Endpoint whose method, path, summary and operationId are source-safe."""
    method = to_http_method(endpoint.get("method", "GET"))
    path = to_path(endpoint.get("path", "/"))
    declared = endpoint.get("operationId") or derived_operation_id(method, path)
    raw_params = [
        safe_parameter(p) for p in endpoint.get("parameters") or [] if isinstance(p, dict)
    ]
    # Sort parameters so required parameters precede optional parameters:
    # 1. path parameters (always required)
    # 2. required query parameters
    # 3. optional query parameters
    sorted_params = sorted(
        raw_params,
        key=lambda p: 0 if p.get("location") == "path" else (1 if p.get("required") else 2),
    )
    return {
        **endpoint,
        "method": method,
        "path": path,
        "summary": to_text(endpoint.get("summary"), fallback=path),
        "operationId": to_identifier(declared, fallback="endpoint"),
        "parameters": sorted_params,
    }
