"""AC-005 support: the strict JSON Schema subset used for tool arguments."""

from __future__ import annotations

from typing import Any

import pytest

from keel_gate.domain.schema import SchemaError, check_schema, validate


@pytest.mark.parametrize(
    "schema",
    [
        "not a mapping",
        {"type": "decimal"},
        {"type": "string", "pattern": "("},
        {"type": "object", "properties": {"a": {"type": "string", "oneOf": []}}},
        {"type": "object", "additionalProperties": {"not": {}}},
        {"type": "array", "items": {"type": "string", "contains": {}}},
    ],
)
def test_bad_schemas_are_refused(schema: Any) -> None:
    with pytest.raises(SchemaError):
        check_schema(schema)


@pytest.mark.parametrize(
    ("value", "schema"),
    [
        (None, {"type": ["string", "null"]}),
        (1.5, {"type": "number", "minimum": 1, "maximum": 2}),
        (True, {"type": "boolean"}),
        ([1, 2], {"type": "array", "minItems": 1, "maxItems": 3, "items": {"type": "integer"}}),
        ("a", {"const": "a"}),
        (5, {"type": "integer", "exclusiveMinimum": 4, "exclusiveMaximum": 6}),
        ({"x": 1}, {"type": "object", "additionalProperties": {"type": "integer"}}),
    ],
)
def test_valid_values_pass(value: Any, schema: dict[str, Any]) -> None:
    assert validate(value, schema) == []


@pytest.mark.parametrize(
    ("value", "schema"),
    [
        (True, {"type": "integer"}),
        (True, {"type": "number"}),
        ("x", {"type": "null"}),
        ([], {"type": "array", "minItems": 1}),
        ([1, 2, 3, 4], {"type": "array", "maxItems": 3}),
        (["a"], {"type": "array", "items": {"type": "integer"}}),
        ("b", {"const": "a"}),
        (0, {"type": "integer", "minimum": 1}),
        (9, {"type": "integer", "maximum": 5}),
        (4, {"type": "integer", "exclusiveMinimum": 4}),
        (6, {"type": "integer", "exclusiveMaximum": 6}),
        ("", {"type": "string", "minLength": 1}),
        ({"x": "y"}, {"type": "object", "additionalProperties": {"type": "integer"}}),
        ({"a": {"b": 1}}, {"type": "object", "properties": {"a": {"type": "object", "required": ["c"]}}}),
        ("x", {"type": "unknown-type"}),
    ],
)
def test_invalid_values_fail(value: Any, schema: dict[str, Any]) -> None:
    assert validate(value, schema) != []
