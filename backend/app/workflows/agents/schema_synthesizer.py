"""Schema-aware sample data synthesis for OpenAPI / JSON Schema specifications.

Replaces deterministic static literals with realistic mock data satisfying
schema constraints: formats (email, uuid, date-time, uri), bounds (minimum,
maximum), string lengths, array item counts, enums, and combinators ($ref, allOf, anyOf).
"""

from __future__ import annotations

from typing import Any


def resolve_ref(ref: str, definitions: dict[str, Any] | None) -> dict[str, Any] | None:
    """Resolve a JSON pointer reference like '#/components/schemas/User' or '#/definitions/Pet'."""
    if not definitions or not isinstance(ref, str):
        return None
    # Strip leading '#/'
    path = ref.lstrip("#/").split("/")
    target: Any = definitions
    for part in path:
        if isinstance(target, dict) and part in target:
            target = target[part]
        else:
            # Check by leaf name directly if nested lookup fails
            leaf = path[-1]
            if leaf in definitions and isinstance(definitions[leaf], dict):
                return definitions[leaf]
            return None
    return target if isinstance(target, dict) else None


def synthesize_schema_data(
    schema: dict[str, Any] | None,
    definitions: dict[str, Any] | None = None,
    depth: int = 0,
    field_name: str | None = None,
) -> Any:
    """Synthesize schema-compliant sample data from an OpenAPI / JSON Schema definition."""
    if not isinstance(schema, dict) or depth > 5:
        return {} if depth > 0 else None

    defs = definitions or {}

    # 1. Direct explicit example, examples, default, or enum
    if "example" in schema:
        return schema["example"]
    if "examples" in schema and isinstance(schema["examples"], list) and schema["examples"]:
        return schema["examples"][0]
    if "default" in schema:
        return schema["default"]
    if schema.get("enum") and isinstance(schema["enum"], list) and schema["enum"]:
        return schema["enum"][0]

    # 2. $ref resolution
    ref = schema.get("$ref")
    if ref and isinstance(ref, str):
        resolved = resolve_ref(ref, defs)
        if resolved:
            return synthesize_schema_data(resolved, defs, depth + 1, field_name)
        ref_name = ref.split("/")[-1]
        return {"name": ref_name.lower()}

    # 3. Schema combinators (allOf, anyOf, oneOf)
    if "allOf" in schema and isinstance(schema["allOf"], list):
        merged: dict[str, Any] = {}
        for sub in schema["allOf"]:
            sub_resolved = sub
            if isinstance(sub, dict) and "$ref" in sub:
                sub_resolved = resolve_ref(sub["$ref"], defs) or sub
            if isinstance(sub_resolved, dict):
                if "properties" in sub_resolved:
                    merged.setdefault("properties", {}).update(sub_resolved.get("properties", {}))
                for key in ("type", "required", "format", "minimum", "maximum"):
                    if key in sub_resolved and key not in merged:
                        merged[key] = sub_resolved[key]
        if merged:
            return synthesize_schema_data(merged, defs, depth + 1, field_name)

    if "anyOf" in schema and isinstance(schema["anyOf"], list) and schema["anyOf"]:
        first = schema["anyOf"][0]
        if isinstance(first, dict):
            return synthesize_schema_data(first, defs, depth + 1, field_name)

    if "oneOf" in schema and isinstance(schema["oneOf"], list) and schema["oneOf"]:
        first = schema["oneOf"][0]
        if isinstance(first, dict):
            return synthesize_schema_data(first, defs, depth + 1, field_name)

    # 4. Type deduction
    s_type = schema.get("type")
    if not s_type and "properties" in schema:
        s_type = "object"
    elif not s_type:
        s_type = "string"
    s_type = str(s_type).lower()

    # 5. Type-specific synthesis
    if s_type == "object" or "properties" in schema:
        obj: dict[str, Any] = {}
        props = schema.get("properties", {})
        if isinstance(props, dict):
            for prop_name, prop_spec in props.items():
                if isinstance(prop_spec, dict):
                    obj[prop_name] = synthesize_schema_data(
                        prop_spec, defs, depth + 1, field_name=prop_name
                    )
        # Handle additionalProperties if no explicit properties were given
        if not obj and schema.get("additionalProperties"):
            add_spec = schema["additionalProperties"]
            if isinstance(add_spec, dict):
                obj["key"] = synthesize_schema_data(add_spec, defs, depth + 1, "key")
        return obj

    elif s_type == "array":
        items_spec = schema.get("items", {})
        min_items = int(schema.get("minItems", 1)) if schema.get("minItems") is not None else 1
        item_count = max(1, min(min_items, 3))
        if isinstance(items_spec, dict) and items_spec:
            return [
                synthesize_schema_data(items_spec, defs, depth + 1, field_name)
                for _ in range(item_count)
            ]
        return ["sample_item"]

    elif s_type in ("integer", "int"):
        min_val = schema.get("minimum")
        max_val = schema.get("maximum")
        excl_min = schema.get("exclusiveMinimum")
        excl_max = schema.get("exclusiveMaximum")

        base_int = 1
        fn = (field_name or "").lower()
        if fn in ("page", "page_number"):
            base_int = 1
        elif fn in ("limit", "size", "per_page", "pagesize"):
            base_int = 20
        elif "port" in fn:
            base_int = 8080
        elif fn in ("count", "quantity"):
            base_int = 5
        elif fn.endswith("id") or fn == "id":
            base_int = 105001

        if min_val is not None:
            base_int = max(base_int, int(min_val))
            if excl_min is True:
                base_int += 1
        if excl_min is not None and isinstance(excl_min, int | float):
            base_int = max(base_int, int(excl_min) + 1)

        if max_val is not None:
            base_int = min(base_int, int(max_val))
            if excl_max is True and base_int >= int(max_val):
                base_int = int(max_val) - 1
        if excl_max is not None and isinstance(excl_max, int | float) and base_int >= int(excl_max):
            base_int = int(excl_max) - 1

        mult = schema.get("multipleOf")
        if mult is not None and mult > 0:
            rem = base_int % int(mult)
            if rem != 0:
                base_int += int(mult) - rem

        return base_int

    elif s_type in ("number", "float", "double"):
        min_val = schema.get("minimum")
        max_val = schema.get("maximum")
        base_num = 1.0
        fn = (field_name or "").lower()
        if any(w in fn for w in ("price", "cost", "amount", "total", "balance")):
            base_num = 9.99
        elif any(w in fn for w in ("rate", "score", "percent", "ratio")):
            base_num = 0.85

        if min_val is not None:
            base_num = max(base_num, float(min_val))
        if max_val is not None:
            base_num = min(base_num, float(max_val))
        return base_num

    elif s_type in ("boolean", "bool"):
        fn = (field_name or "").lower()
        if any(w in fn for w in ("disabled", "deleted", "archived", "blocked", "is_deleted")):
            return False
        return True

    else:  # string
        s_format = schema.get("format", "").lower()
        fn = (field_name or "").lower()

        # Format-based synthesis
        if s_format == "email":
            val = "user@example.com"
        elif s_format == "uuid":
            val = "123e4567-e89b-12d3-a456-426614174000"
        elif s_format == "date-time":
            val = "2026-01-01T12:00:00Z"
        elif s_format == "date":
            val = "2026-01-01"
        elif s_format == "time":
            val = "12:00:00"
        elif s_format in ("uri", "url"):
            val = "https://api.example.com/v1/resource"
        elif s_format == "ipv4":
            val = "192.168.1.1"
        elif s_format == "ipv6":
            val = "2001:db8::1"
        elif s_format == "hostname":
            val = "api.example.com"
        elif s_format in ("byte", "binary"):
            val = "dGVzdA=="
        elif s_format == "password":
            val = "Secret123!"
        # Field-name heuristics if format is absent
        elif "email" in fn:
            val = "user@example.com"
        elif "uuid" in fn:
            val = "123e4567-e89b-12d3-a456-426614174000"
        elif fn.endswith("_id") or fn == "id":
            val = f"{fn}_123"
        elif any(w in fn for w in ("url", "uri", "website", "avatar", "webhook")):
            val = "https://api.example.com/v1/resource"
        elif any(w in fn for w in ("phone", "telephone", "mobile")):
            val = "+1-555-0100"
        elif any(w in fn for w in ("created_at", "updated_at", "timestamp", "datetime")):
            val = "2026-01-01T12:00:00Z"
        elif "date" in fn:
            val = "2026-01-01"
        elif "username" in fn or fn == "user":
            val = "weaver_test_user"
        elif "status" in fn:
            val = "available"
        elif "name" in fn:
            val = f"sample_{fn}"
        elif field_name:
            val = f"sample_{field_name}"
        else:
            val = "sample_value"

        # Apply minLength / maxLength constraints
        min_len = schema.get("minLength")
        max_len = schema.get("maxLength")
        if min_len is not None and len(val) < int(min_len):
            pad_needed = int(min_len) - len(val)
            val = val + ("_sample" * ((pad_needed // 7) + 1))[:pad_needed]
        if max_len is not None and len(val) > int(max_len):
            val = val[:int(max_len)]

        return val
