"""Amendment A1, AC-185 to AC-188: draft manifests from existing tool definitions."""

from __future__ import annotations

from typing import Any

import pytest

from keel_gate.domain.draft import draft_manifest
from keel_gate.domain.manifest import Manifest, ManifestError
from keel_gate.domain.models import Verdict
from keel_gate.gate import Gate, GateSettings
from tests.factories import make_call, make_session

ORDER_SCHEMA = {
    "type": "object",
    "properties": {"order_id": {"type": "string"}},
    "required": ["order_id"],
}

MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "lookup_order",
        "description": "Find an order.",
        "inputSchema": ORDER_SCHEMA,
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "delete_customer",
        "description": "Delete a customer and all their data.",
        "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}},
        "annotations": {"readOnlyHint": False, "destructiveHint": True},
    },
    {
        "name": "search_web",
        "description": "Search the web.",
        "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "export_all",
        "description": "Export every record.",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {"fmt": {"oneOf": [{"const": "csv"}, {"const": "json"}]}},
        },
    },
]


def _spec(manifest: Manifest, name: str):  # type: ignore[no-untyped-def]
    spec = manifest.get(name)
    assert spec is not None
    return spec


def test_ac_185_mcp_tools_list_becomes_a_loadable_manifest() -> None:
    draft = draft_manifest(MCP_TOOLS, fmt="mcp", server="crm")

    manifest = Manifest.from_document(draft.document())

    assert manifest.names == ["crm.delete_customer", "crm.export_all", "crm.lookup_order", "crm.search_web"]


def test_ac_185_claude_tool_definitions_are_drafted() -> None:
    tools = [{"name": "crm__lookup_order", "description": "Find an order.", "input_schema": ORDER_SCHEMA}]

    manifest = Manifest.from_document(draft_manifest(tools, fmt="claude").document())

    assert manifest.names == ["crm.lookup_order"]


@pytest.mark.parametrize(
    "tool",
    [
        {"type": "function", "function": {"name": "lookup_order", "description": "Find.", "parameters": ORDER_SCHEMA}},
        {"type": "function", "name": "lookup_order", "description": "Find.", "parameters": ORDER_SCHEMA},
    ],
)
def test_ac_185_openai_function_tools_are_drafted(tool: dict[str, Any]) -> None:
    manifest = Manifest.from_document(draft_manifest([tool], fmt="openai").document())

    assert manifest.names == ["lookup_order"]


def test_ac_186_read_only_hint_maps_to_read_only() -> None:
    manifest = Manifest.from_document(draft_manifest(MCP_TOOLS, fmt="mcp", server="crm").document())

    spec = _spec(manifest, "crm.lookup_order")

    assert (spec.read_only, spec.state_changing, spec.destructive) == (True, False, False)


def test_ac_186_destructive_hint_maps_to_destructive() -> None:
    manifest = Manifest.from_document(draft_manifest(MCP_TOOLS, fmt="mcp", server="crm").document())

    spec = _spec(manifest, "crm.delete_customer")

    assert (spec.state_changing, spec.destructive, spec.reversible) == (True, True, False)


def test_ac_186_open_world_hint_maps_to_remote_and_egress() -> None:
    manifest = Manifest.from_document(draft_manifest(MCP_TOOLS, fmt="mcp", server="crm").document())

    spec = _spec(manifest, "crm.search_web")

    assert (spec.remote, spec.egress, spec.result_label) == (True, True, "untrusted")


def test_ac_186_no_hints_means_ask_never_a_guess_from_the_name() -> None:
    tools = [{"name": "delete_everything", "description": "x", "inputSchema": {"type": "object"}}]
    manifest = Manifest.from_document(draft_manifest(tools, fmt="mcp").document())

    spec = _spec(manifest, "delete_everything")

    assert (spec.state_changing, spec.reversible, spec.destructive) == (True, False, False)


def test_ac_187_unsupported_schema_keywords_are_removed_and_noted() -> None:
    draft = draft_manifest(MCP_TOOLS, fmt="mcp", server="crm")

    notes = draft.notes["crm.export_all"]

    assert any("$schema" in note for note in notes)
    assert any("oneOf" in note for note in notes)
    assert "oneOf" not in str(draft.document()["tools"]["crm.export_all"]["schema"])


def test_ac_187_a_missing_hint_is_noted_for_review() -> None:
    draft = draft_manifest(MCP_TOOLS, fmt="mcp", server="crm")

    assert any("no safety hints" in note for note in draft.notes["crm.export_all"])


def test_ac_188_a_draft_document_is_marked_draft() -> None:
    manifest = Manifest.from_document(draft_manifest(MCP_TOOLS, fmt="mcp", server="crm").document())

    assert manifest.draft is True


def test_ac_188_the_gate_refuses_a_draft_in_enforce_mode() -> None:
    manifest = Manifest.from_document(draft_manifest(MCP_TOOLS, fmt="mcp", server="crm").document())

    with pytest.raises(ManifestError, match="draft"):
        Gate(manifest)


def test_ac_188_the_gate_loads_a_draft_in_observe_mode() -> None:
    manifest = Manifest.from_document(draft_manifest(MCP_TOOLS, fmt="mcp", server="crm").document())
    gate = Gate(manifest, settings=GateSettings(mode="observe"))

    decision = gate.decide(make_call("crm.export_all", {"fmt": "csv"}), make_session())

    assert (decision.verdict, decision.observed_verdict) == (Verdict.ALLOW, Verdict.ASK)


def test_ac_188_a_reviewed_document_is_not_a_draft() -> None:
    document = draft_manifest(MCP_TOOLS, fmt="mcp", server="crm").document()
    document["draft"] = False

    gate = Gate(Manifest.from_document(document))

    assert gate.decide(make_call("crm.lookup_order", {"order_id": "7"}), make_session()).verdict is Verdict.ALLOW


def test_ac_188_a_document_must_list_tools() -> None:
    with pytest.raises(ManifestError):
        Manifest.from_document({"draft": True})
