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


def to_literal(value: Any) -> str:
    """A complete string literal (`json.dumps` output is a valid Python and JS literal)."""
    return json.dumps(str(value))


def derived_operation_id(method: str, path: str) -> str:
    """Operation name for a spec endpoint that declares no operationId."""
    return f"{method}_{to_path(path).replace('/', '_').replace('{', '').replace('}', '')}"


def safe_parameter(param: dict[str, Any]) -> dict[str, Any]:
    """Parameter whose fields are safe for argument names and annotations."""
    return {
        **param,
        "name": to_identifier(param.get("name"), fallback="param"),
        "type": to_type_name(param.get("type")),
        "location": to_identifier(param.get("location"), fallback="query"),
        "required": bool(param.get("required")),
    }


def safe_endpoint(endpoint: dict[str, Any]) -> dict[str, Any]:
    """Endpoint whose method, path, summary and operationId are source-safe."""
    method = to_http_method(endpoint.get("method", "GET"))
    path = to_path(endpoint.get("path", "/"))
    declared = endpoint.get("operationId") or derived_operation_id(method, path)
    return {
        **endpoint,
        "method": method,
        "path": path,
        "summary": to_text(endpoint.get("summary"), fallback=path),
        "operationId": to_identifier(declared, fallback="endpoint"),
        "parameters": [
            safe_parameter(p) for p in endpoint.get("parameters") or [] if isinstance(p, dict)
        ],
    }
