"""A small, strict JSON Schema subset for tool arguments (AC-005).

Tool schemas in a manifest only need simple shapes. Supporting a small subset keeps the gate fast and free of heavy
dependencies. Any keyword outside the subset is refused when the manifest loads, so a schema can never be silently
ignored (fail closed).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

SUPPORTED = frozenset(
    {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "enum",
        "const",
        "pattern",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "items",
        "minItems",
        "maxItems",
        "description",
        "title",
        "default",
        "examples",
        "format",
    }
)
TYPES = frozenset({"string", "integer", "number", "boolean", "object", "array", "null"})


class SchemaError(ValueError):
    """The schema itself is invalid or uses an unsupported keyword."""


def check_schema(schema: Any, path: str = "$") -> None:
    if not isinstance(schema, Mapping):
        raise SchemaError(f"{path}: a schema must be an object")
    unknown = set(schema) - SUPPORTED
    if unknown:
        raise SchemaError(f"{path}: unsupported schema keyword(s): {', '.join(sorted(unknown))}")
    types = schema.get("type")
    for t in types if isinstance(types, list) else [types] if types is not None else []:
        if t not in TYPES:
            raise SchemaError(f"{path}: unknown type {t!r}")
    if "pattern" in schema:
        try:
            re.compile(schema["pattern"])
        except (re.error, TypeError) as exc:
            raise SchemaError(f"{path}: bad pattern: {exc}") from exc
    for name, sub in (schema.get("properties") or {}).items():
        check_schema(sub, f"{path}.{name}")
    extra = schema.get("additionalProperties")
    if isinstance(extra, Mapping):
        check_schema(extra, f"{path}.*")
    if "items" in schema:
        check_schema(schema["items"], f"{path}[]")


def _type_ok(value: Any, expected: str) -> bool:
    match expected:
        case "string":
            return isinstance(value, str)
        case "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        case "number":
            return isinstance(value, int | float) and not isinstance(value, bool)
        case "boolean":
            return isinstance(value, bool)
        case "object":
            return isinstance(value, Mapping)
        case "array":
            return isinstance(value, list | tuple)
        case "null":
            return value is None
    return False


def validate(value: Any, schema: Mapping[str, Any], path: str = "$") -> list[str]:
    """Return a list of problems; an empty list means the value is valid."""
    errors: list[str] = []
    types = schema.get("type")
    if types is not None:
        allowed = types if isinstance(types, list) else [types]
        if not any(_type_ok(value, t) for t in allowed):
            return [f"{path}: expected {' or '.join(allowed)}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: not one of the allowed values")
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must be {schema['const']!r}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: too short")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: too long")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            errors.append(f"{path}: does not match the required pattern")
    if isinstance(value, int | float) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: below the minimum")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: above the maximum")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: not above the minimum")
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            errors.append(f"{path}: not below the maximum")
    if isinstance(value, Mapping):
        errors.extend(_validate_object(value, schema, path))
    if isinstance(value, list | tuple):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: too few items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: too many items")
        if "items" in schema:
            for i, item in enumerate(value):
                errors.extend(validate(item, schema["items"], f"{path}[{i}]"))
    return errors


def _validate_object(value: Mapping[str, Any], schema: Mapping[str, Any], path: str) -> list[str]:
    errors = [f"{path}.{key}: is required" for key in schema.get("required", []) if key not in value]
    properties: Mapping[str, Any] = schema.get("properties") or {}
    extra = schema.get("additionalProperties", True)
    for key, item in value.items():
        if key in properties:
            errors.extend(validate(item, properties[key], f"{path}.{key}"))
        elif extra is False:
            errors.append(f"{path}.{key}: is not allowed")
        elif isinstance(extra, Mapping):
            errors.extend(validate(item, extra, f"{path}.{key}"))
    return errors
