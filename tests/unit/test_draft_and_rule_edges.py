"""Edge cases for draft cleaning (AC-185, AC-187) and rule validation (AC-190, AC-194)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from keel_gate.domain.draft import draft_manifest
from keel_gate.domain.manifest import ManifestError
from keel_gate.domain.rules import CustomRule, rules_from_mapping


def _notes_for(schema: Any) -> list[str]:
    draft = draft_manifest([{"name": "t", "description": "d", "inputSchema": schema}], fmt="mcp")
    return draft.notes["t"]


@pytest.mark.parametrize(
    ("schema", "fragment"),
    [
        ({"type": "object", "properties": {"a": {"type": "decimal"}}}, "unknown type"),
        ({"type": "object", "properties": {"a": {"type": "string", "pattern": "(?<n>x)"}}}, "pattern"),
        ({"type": "object", "properties": "nope"}, "invalid properties"),
        ({"type": "object", "properties": {"a": {"type": "array", "items": [{"type": "string"}]}}}, "tuple-style"),
        ({"type": "object", "required": "a"}, "invalid required"),
        ({"type": "object", "properties": {"a": "not a schema"}}, "non-object schema"),
        ({"type": "string"}, "set the schema type to object"),
        ({"type": "object", "additionalProperties": {"type": "string", "format": "x", "if": {}}}, "'if'"),
    ],
)
def test_ac_187_every_schema_repair_is_noted(schema: Any, fragment: str) -> None:
    notes = _notes_for(schema)

    assert any(fragment in note for note in notes), notes


def test_ac_185_a_missing_description_is_noted() -> None:
    draft = draft_manifest([{"name": "t", "inputSchema": {"type": "object"}}], fmt="mcp")

    assert any("no description" in note for note in draft.notes["t"])


def test_ac_185_a_missing_schema_becomes_an_empty_object() -> None:
    draft = draft_manifest([{"name": "t", "description": "d"}], fmt="claude")

    assert draft.tools["t"]["schema"] == {"type": "object"}


@pytest.mark.parametrize(
    "tools",
    [
        [{"description": "no name"}],
        [{"name": "same", "description": "a"}, {"name": "same", "description": "b"}],
    ],
)
def test_ac_185_unusable_definitions_are_refused(tools: list[dict[str, Any]]) -> None:
    with pytest.raises(ManifestError):
        draft_manifest(tools, fmt="mcp")


# --------------------------------------------------------------------------- rules


@pytest.mark.parametrize(
    "fields",
    [
        {"id": "bad id", "tool": "shell", "verdict": "deny", "reason": "x"},
        {"id": "ru_a", "tool": "shell", "verdict": "deny", "reason": "x", "surprise": 1},
        {"id": "ru_a", "tool": "shell", "verdict": "deny", "reason": "x", "match": "x" * 501},
        {"id": "ru_a", "tool": "shell", "verdict": "deny", "reason": "x", "match_arg": "a b"},
        {"id": "ru_a", "tool": "shell", "verdict": "deny", "reason": "x", "enabled": "yes"},
        {"id": "ru_a", "tool": "shell", "verdict": "deny", "reason": "x", "expires_at": "next friday"},
        {"id": "ru_a", "tool": "shell", "verdict": "deny", "reason": "x", "expires_at": 1234},
    ],
)
def test_ac_190_every_rule_field_is_checked(fields: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="invalid rule"):
        CustomRule.create(**fields)


@pytest.mark.parametrize(
    "value",
    ["2026-11-16", "2026-11-16T00:00:00", date(2026, 11, 16), datetime(2026, 11, 16, tzinfo=UTC)],
)
def test_ac_194_expiry_accepts_dates_and_times_and_assumes_utc(value: Any) -> None:
    rule = CustomRule.create(id="ru_a", tool="shell", verdict="deny", reason="x", expires_at=value)

    assert rule.expires_at == datetime(2026, 11, 16, tzinfo=UTC)


@pytest.mark.parametrize(
    "data",
    [
        "not a mapping",
        {"rules": "not a list"},
        {"rules": ["not a mapping"]},
        {"rules": [{"id": "ru_a", "tool": "x", "verdict": "deny", "reason": "r"}] * 2},
    ],
)
def test_ac_190_a_broken_rules_file_is_refused(data: Any) -> None:
    with pytest.raises(ValueError, match="invalid rule"):
        rules_from_mapping(data)


def test_ac_190_a_rule_without_an_id_gets_a_stable_one() -> None:
    block = {"rules": [{"tool": "shell", "verdict": "deny", "reason": "r"}]}

    first, second = rules_from_mapping(block)[0], rules_from_mapping(block)[0]

    assert first.id == second.id
    assert first.id.startswith("ru_")


def test_ac_190_a_rule_round_trips_through_plain_data() -> None:
    rule = CustomRule.create(id="ru_a", tool="shell", verdict="ask", reason="x", match="npm *", expires_at="2026-11-16")

    again = CustomRule.create(**rule.to_mapping())

    assert again == rule
