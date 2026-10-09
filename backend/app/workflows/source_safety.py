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

from app.core.constants import DEFAULT_BASE_URL

HTTP_METHODS = frozenset(
    {"get", "put", "post", "patch", "delete", "options", "head", "trace"}
)

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


# Words that cannot name a function, parameter or class in JavaScript/TypeScript. The
# same identifier is emitted into both the Python and the TypeScript SDK, so a name must
# be legal in both (`export async function delete(` is a syntax error).
_JS_RESERVED = frozenset(
    {
        "break", "case", "catch", "class", "const", "continue", "debugger", "default",
        "delete", "do", "else", "enum", "export", "extends", "false", "finally", "for",
        "function", "if", "implements", "import", "in", "instanceof", "interface", "let",
        "new", "null", "package", "private", "protected", "public", "return", "static",
        "super", "switch", "this", "throw", "true", "try", "typeof", "var", "void",
        "while", "with", "yield", "await", "arguments", "eval",
    }
)


def _is_reserved(name: str) -> bool:
    return iskeyword(name) or name in _JS_RESERVED


def to_identifier(value: Any, *, fallback: str, limit: int = 60) -> str:
    """Shape a value into an identifier legal in both Python and TypeScript."""
    name = _UNSAFE_IDENT.sub("_", _as_str(value).strip())[:limit].rstrip("_")
    if not name or not (name[0].isalpha() or name[0] == "_") or _is_reserved(name):
        return f"{fallback}_{name}"[:limit] if name else fallback
    return name


_WORD_SPLIT = re.compile(r"[^A-Za-z0-9]+")


def to_class_name(value: Any, *, fallback: str = "Model", limit: int = 80) -> str:
    """PascalCase class/interface name from any text (`health-check` -> `HealthCheck`)."""
    words = [w for w in _WORD_SPLIT.split(_as_str(value)) if w]
    name = "".join(w[:1].upper() + w[1:] for w in words)[:limit]
    if not name:
        return fallback
    if not name[0].isalpha():
        name = f"{fallback}{name}"[:limit]
    return name


def client_class_name(title: Any) -> str:
    """The generated SDK's client class, shared by the code and export agents."""
    display = to_display_name(title, fallback="")
    if not display:
        return "APIClient"
    return to_class_name(display, fallback="Api") + "Client"


def to_env_prefix(title: Any) -> str:
    """`UPPER_SNAKE` prefix for the SDK's environment variables (`process.env.<X>_API_KEY`)."""
    words = [w for w in _WORD_SPLIT.split(_as_str(title)) if w]
    prefix = "_".join(w.upper() for w in words)[:40] or "API"
    if not prefix[0].isalpha():
        prefix = f"API_{prefix}"
    return prefix


def to_package_name(title: Any, *, fallback: str = "api") -> str:
    """Lowercase, hyphenated distribution name (PyPI/npm/GitHub repo safe)."""
    words = [w.lower() for w in _WORD_SPLIT.split(_as_str(title)) if w]
    name = "-".join(words)[:60].strip("-")
    return name or fallback


def to_module_name(title: Any, *, fallback: str = "api") -> str:
    """Lowercase, underscored import name."""
    return to_identifier(to_package_name(title, fallback=fallback).replace("-", "_"), fallback=fallback)


_VERSION_CORE = re.compile(r"\d+(?:\.\d+){0,2}")


def to_package_version(value: Any, *, fallback: str = "0.1.0") -> str:
    """A `MAJOR.MINOR.PATCH` that is valid for both PEP 440 and npm semver.

    API versions are free text (`v1`, `2023-10-16`, `1.0.0"; import os; ...`); only the
    leading numeric core is kept, padded to three components.
    """
    match = _VERSION_CORE.search(_as_str(value))
    if not match:
        return fallback
    parts = [str(int(p)) for p in match.group(0).split(".")]
    while len(parts) < 3:
        parts.append("0")
    return ".".join(parts)


_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$")


def to_email(value: Any, *, fallback: str) -> str:
    email = _as_str(value).strip()
    return email if _EMAIL.match(email) else fallback


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


# Names the generated method bodies already use; a parameter called `url` or `body`
# would shadow them (or repeat an argument name, which is a SyntaxError).
_RESERVED_ARGUMENTS = frozenset(
    {"self", "body", "url", "params", "json_body", "client", "c", "headers", "config"}
)


def safe_parameter(param: dict[str, Any]) -> dict[str, Any]:
    """Parameter whose fields are safe for argument names and annotations.

    `name` is the sanitized argument name. The name the API expects on the wire is kept
    separately: `wire_name` (query keys, emitted only as a quoted literal) and
    `path_token` (the `{placeholder}` exactly as it survives `to_path`), so `page-size`
    is still sent as `page-size` and `{pet-id}` is still substituted.
    """
    loc = to_identifier(param.get("location"), fallback="query")
    req = bool(param.get("required")) or (loc == "path")
    raw_name = _as_str(param.get("name")).strip()
    name = to_identifier(raw_name, fallback="param")
    if name in _RESERVED_ARGUMENTS:
        name = f"{name}_param"
    return {
        **param,
        "name": name,
        "wire_name": raw_name or name,
        "path_token": "{" + _UNSAFE_PATH.sub("", raw_name) + "}",
        "type": to_type_name(param.get("type")),
        "location": loc,
        "required": req,
    }


def _dedupe_names(params: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`page_size` and `page-size` sanitize to the same argument; suffix the repeats."""
    seen: set[str] = set()
    result = []
    for param in params:
        name = param["name"]
        candidate, n = name, 2
        while candidate in seen:
            candidate, n = f"{name}_{n}", n + 1
        seen.add(candidate)
        result.append({**param, "name": candidate})
    return result


def safe_endpoint(endpoint: dict[str, Any]) -> dict[str, Any]:
    """Endpoint whose method, path, summary and operationId are source-safe."""
    method = to_http_method(endpoint.get("method", "GET"))
    path = to_path(endpoint.get("path", "/"))
    declared = endpoint.get("operationId") or derived_operation_id(method, path)
    raw_params = _dedupe_names(
        [safe_parameter(p) for p in endpoint.get("parameters") or [] if isinstance(p, dict)]
    )
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
