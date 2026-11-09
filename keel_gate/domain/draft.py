"""Draft manifests from tool definitions a team already has (Amendment A1, AC-185 to AC-188).

Inputs: MCP `tools/list` entries, Claude API tool definitions, or OpenAI function tools.
Rules:
- MCP hints are used as given: readOnlyHint, destructiveHint, openWorldHint.
- A tool with no hints becomes state-changing and not reversible, so calls to it ask a human. Names are never used to
  guess risk, because names can lie.
- Schema keywords outside keel-gate's subset are removed, and every removal becomes a review note.
- The result is marked draft: true; the gate loads it only in observe mode until a human reviews it.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from keel_gate.domain.manifest import Manifest, ManifestError
from keel_gate.domain.naming import tool_name
from keel_gate.domain.schema import SUPPORTED, TYPES

DraftFormat = Literal["mcp", "claude", "openai"]


@dataclass
class Draft:
    tools: dict[str, dict[str, Any]] = field(default_factory=dict)
    notes: dict[str, list[str]] = field(default_factory=dict)

    def document(self) -> dict[str, Any]:
        """The manifest file content, marked as a draft."""
        return {"draft": True, "tools": copy.deepcopy(self.tools)}


def _clean_schema(schema: Any, path: str, notes: list[str]) -> dict[str, Any]:
    if not isinstance(schema, Mapping):
        notes.append(f"replaced a non-object schema at {path} with an empty one")
        return {}
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key not in SUPPORTED:
            notes.append(f"removed schema keyword '{key}' at {path}")
            continue
        if key == "type":
            types = value if isinstance(value, list) else [value]
            if not all(isinstance(t, str) and t in TYPES for t in types):
                notes.append(f"removed unknown type {value!r} at {path}")
                continue
        if key == "pattern":
            try:
                re.compile(value)
            except (re.error, TypeError):
                notes.append(f"removed a pattern Python cannot read at {path}")
                continue
        if key == "properties":
            if not isinstance(value, Mapping):
                notes.append(f"removed invalid properties at {path}")
                continue
            value = {name: _clean_schema(sub, f"{path}.{name}", notes) for name, sub in value.items()}
        elif key in ("additionalProperties", "items") and not isinstance(value, bool):
            if key == "items" and isinstance(value, list):
                notes.append(f"removed tuple-style items at {path}")
                continue
            value = _clean_schema(value, f"{path}.{key}", notes)
        elif key == "required" and not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
            notes.append(f"removed invalid required list at {path}")
            continue
        out[key] = value
    return out


def _extract(tool: Mapping[str, Any], fmt: DraftFormat) -> tuple[str, str, Any, Mapping[str, Any]]:
    if fmt == "mcp":
        annotations = tool.get("annotations") or {}
        description = tool.get("description") or tool.get("title") or annotations.get("title") or ""
        return str(tool.get("name", "")), str(description), tool.get("inputSchema"), annotations
    if fmt == "claude":
        return str(tool.get("name", "")), str(tool.get("description") or ""), tool.get("input_schema"), {}
    nested = tool.get("function")
    function: Mapping[str, Any] = nested if isinstance(nested, Mapping) else tool
    return str(function.get("name", "")), str(function.get("description") or ""), function.get("parameters"), {}


def draft_manifest(tools: Sequence[Mapping[str, Any]], fmt: DraftFormat, server: str | None = None) -> Draft:
    draft = Draft()
    for tool in tools:
        raw_name, description, schema, annotations = _extract(tool, fmt)
        if not raw_name:
            raise ManifestError("a tool definition has no name")
        name = f"{server}.{raw_name}" if (server and fmt == "mcp") else tool_name(raw_name)
        if name in draft.tools:
            raise ManifestError(f"two tools are named {name!r}")
        notes: list[str] = []
        if not description.strip():
            description = f"{name} (no description given)"
            notes.append("no description: write one before pinning")
        cleaned = _clean_schema(schema if schema is not None else {"type": "object"}, "$", notes)
        if cleaned.get("type") != "object":
            cleaned["type"] = "object"
            notes.append("set the schema type to object (tool arguments are always an object)")

        read_only = annotations.get("readOnlyHint") is True
        destructive = annotations.get("destructiveHint") is True and not read_only
        open_world = annotations.get("openWorldHint") is True
        entry: dict[str, Any] = {
            "description": description,
            "schema": cleaned,
            "read_only": read_only,
            "state_changing": not read_only,
            "reversible": read_only,
        }
        if destructive:
            entry["destructive"] = True
            notes.append("destructiveHint: calls are blocked (T3) until you change this entry")
        if open_world:
            entry.update(remote=True, egress=True, result_label="untrusted")
            notes.append("openWorldHint: remote + egress, and its results are treated as untrusted")
        if not any(key in annotations for key in ("readOnlyHint", "destructiveHint", "openWorldHint")):
            notes.append("no safety hints: drafted as state-changing and not reversible (calls ask a human)")
        draft.tools[name] = entry
        draft.notes[name] = notes
    Manifest.from_mapping(draft.tools)  # fail early if the draft could never load
    return draft
