"""Unit tests for schema-aware data synthesis (Item 16)."""

from __future__ import annotations

import re
import uuid

from app.workflows.agents.schema_synthesizer import resolve_ref, synthesize_schema_data
from app.workflows.agents.test_agent import _generate_deterministic_fixture


def test_resolve_ref_components_and_defs():
    """resolve_ref navigates OpenAPI 3 / JSON Schema pointer references."""
    defs = {
        "components": {
            "schemas": {
                "User": {"type": "object", "properties": {"id": {"type": "integer"}}},
            }
        },
        "Order": {"type": "object", "properties": {"amount": {"type": "number"}}},
    }

    assert resolve_ref("#/components/schemas/User", defs) == {
        "type": "object",
        "properties": {"id": {"type": "integer"}},
    }
    assert resolve_ref("#/definitions/Order", defs) == {
        "type": "object",
        "properties": {"amount": {"type": "number"}},
    }
    assert resolve_ref("#/missing", defs) is None


def test_synthesize_explicit_values_priority():
    """Explicit example, default, or enum take immediate precedence."""
    assert synthesize_schema_data({"type": "string", "example": "custom-val"}) == "custom-val"
    assert synthesize_schema_data({"type": "string", "examples": ["ex1", "ex2"]}) == "ex1"
    assert synthesize_schema_data({"type": "integer", "default": 42}) == 42
    assert synthesize_schema_data({"type": "string", "enum": ["first", "second"]}) == "first"


def test_synthesize_string_formats():
    """String formats produce realistic valid values."""
    email = synthesize_schema_data({"type": "string", "format": "email"})
    assert "@" in email and "." in email

    val_uuid = synthesize_schema_data({"type": "string", "format": "uuid"})
    uuid.UUID(val_uuid)  # asserts valid UUID

    dt = synthesize_schema_data({"type": "string", "format": "date-time"})
    assert "T" in dt and dt.endswith("Z")

    d = synthesize_schema_data({"type": "string", "format": "date"})
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", d)

    url = synthesize_schema_data({"type": "string", "format": "uri"})
    assert url.startswith("https://")

    ip = synthesize_schema_data({"type": "string", "format": "ipv4"})
    assert re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip)


def test_synthesize_string_field_heuristics():
    """When format is omitted, property names infer reasonable values."""
    assert synthesize_schema_data({"type": "string"}, field_name="user_email") == "user@example.com"
    assert synthesize_schema_data({"type": "string"}, field_name="avatar_url").startswith("https://")
    assert synthesize_schema_data({"type": "string"}, field_name="account_id") == "account_id_123"


def test_synthesize_string_length_bounds():
    """minLength pads strings and maxLength truncates strings."""
    min_res = synthesize_schema_data({"type": "string", "minLength": 25}, field_name="code")
    assert len(min_res) >= 25

    max_res = synthesize_schema_data({"type": "string", "maxLength": 5}, field_name="long_name")
    assert len(max_res) <= 5


def test_synthesize_integer_bounds_and_heuristics():
    """Integers respect minimum/maximum, exclusive bounds, multipleOf, and field heuristics."""
    # Minimum bound
    val_min = synthesize_schema_data({"type": "integer", "minimum": 100})
    assert val_min >= 100

    # Exclusive minimum
    val_excl = synthesize_schema_data({"type": "integer", "minimum": 100, "exclusiveMinimum": True})
    assert val_excl > 100

    # Maximum bound
    val_max = synthesize_schema_data({"type": "integer", "maximum": -10})
    assert val_max <= -10

    # multipleOf
    val_mult = synthesize_schema_data({"type": "integer", "minimum": 13, "multipleOf": 5})
    assert val_mult % 5 == 0
    assert val_mult >= 13

    # Semantic names
    assert synthesize_schema_data({"type": "integer"}, field_name="limit") == 20
    assert synthesize_schema_data({"type": "integer"}, field_name="port") == 8080


def test_synthesize_number_bounds():
    """Float/Number types respect minimum, maximum, and semantic keywords."""
    price = synthesize_schema_data({"type": "number"}, field_name="total_price")
    assert price == 9.99

    bounded = synthesize_schema_data({"type": "number", "minimum": 50.5, "maximum": 100.0})
    assert 50.5 <= bounded <= 100.0


def test_synthesize_boolean():
    """Booleans default to True unless named like a deletion/disabled flag."""
    assert synthesize_schema_data({"type": "boolean"}, field_name="is_active") is True
    assert synthesize_schema_data({"type": "boolean"}, field_name="is_deleted") is False


def test_synthesize_array():
    """Arrays respect minItems and recursively synthesize valid item schemas."""
    schema = {
        "type": "array",
        "minItems": 2,
        "items": {"type": "string", "format": "email"},
    }
    arr = synthesize_schema_data(schema)
    assert isinstance(arr, list)
    assert len(arr) >= 2
    assert all("@" in x for x in arr)


def test_synthesize_object_and_combinators():
    """Objects synthesize properties, resolve $ref, and merge allOf schemas."""
    defs = {
        "Address": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "example": "San Francisco"},
                "zip": {"type": "string", "minLength": 5},
            },
        }
    }

    schema = {
        "type": "object",
        "allOf": [
            {
                "properties": {
                    "email": {"type": "string", "format": "email"},
                }
            },
            {
                "properties": {
                    "address": {"$ref": "#/Address"},
                }
            },
        ],
    }

    obj = synthesize_schema_data(schema, definitions=defs)
    assert obj["email"] == "user@example.com"
    assert obj["address"]["city"] == "San Francisco"
    assert len(obj["address"]["zip"]) >= 5


def test_generate_deterministic_fixture_integration():
    """_generate_deterministic_fixture generates rich, compliant endpoint fixtures."""
    ep = {
        "method": "POST",
        "path": "/users",
        "parameters": [
            {"name": "org_id", "location": "query", "type": "string", "format": "uuid"},
            {"name": "page_size", "location": "query", "type": "integer", "minimum": 10},
        ],
        "request_schema": {
            "type": "object",
            "properties": {
                "email": {"type": "string", "format": "email"},
                "age": {"type": "integer", "minimum": 21},
                "website": {"type": "string", "format": "uri"},
            },
        },
        "response_schemas": {"201": {"type": "object"}},
    }

    fixture = _generate_deterministic_fixture(ep)
    req = fixture["request"]

    # Parameter formats
    uuid.UUID(req["params"]["org_id"])
    assert req["params"]["page_size"] >= 10

    # Body formats & bounds
    assert "@" in req["body"]["email"]
    assert req["body"]["age"] >= 21
    assert req["body"]["website"].startswith("https://")
    assert fixture["expected_status"] == 201
