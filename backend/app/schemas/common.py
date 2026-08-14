"""Shared schema base classes and the cursor-pagination envelope from `API.md §4`."""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """Base for every **request** schema.

    `extra="forbid"` implements `Security.md §10`: "unknown fields rejected, not silently
    ignored". Silently ignoring an unknown field is how a typo'd `is_admin` looks like it
    worked.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ResponseModel(BaseModel):
    """Base for every **response** schema.

    Responses are permissive about extra attributes on the source object (`from_attributes`)
    so an ORM model can be serialized directly, but only declared fields are emitted — a
    column added to a model never leaks into an API response by accident.
    """

    model_config = ConfigDict(from_attributes=True)


class PaginationMeta(ResponseModel):
    next_cursor: str | None = None
    has_more: bool = False
    limit: int


class Page[T](ResponseModel):
    """`{"data": [...], "pagination": {...}}` per `API.md §4`."""

    data: list[T]
    pagination: PaginationMeta


class PaginationParams(StrictModel):
    limit: int = Field(default=25, ge=1, le=100)
    cursor: str | None = None


def encode_cursor(payload: dict[str, Any]) -> str:
    """Opaque base64 cursor, matching the `eyJpZCI6...` form in `API.md §4`.

    Opaque by convention only — it is not signed, so a client could decode and tamper
    with it. That is acceptable because the cursor only ever narrows a result set that is
    already filtered by the caller's own org scope; a forged cursor cannot reach another
    tenant's rows.
    """
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(cursor: str) -> dict[str, Any]:
    """Decode a cursor, returning `{}` for anything malformed.

    A bad cursor degrades to "start from the beginning" rather than raising, so a stale
    bookmark in a client does not become a 400.
    """
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode())
        parsed = json.loads(decoded)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
