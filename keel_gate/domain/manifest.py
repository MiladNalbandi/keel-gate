"""The tool manifest: what each tool is, how risky it is, and its pinned definition (AC-003, AC-090, AC-091)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, get_args

from keel_gate.domain.canonical import canonical_json, sha256_hex
from keel_gate.domain.schema import SchemaError, check_schema

ResultLabel = Literal["trusted", "untrusted", "secret"]
ToolKind = Literal["generic", "shell"]

_REQUIRED = ("description", "read_only", "state_changing", "reversible", "schema")
_FLAGS = ("sensitive", "remote", "egress", "mandate_ok", "destructive")
_OPTIONAL = (*_FLAGS, "result_label", "kind", "sql_arg")


class ManifestError(ValueError):
    """The manifest is invalid. The gate refuses to start with it (fail closed)."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    read_only: bool
    state_changing: bool
    reversible: bool
    schema: Mapping[str, Any] = field(repr=False)
    sensitive: bool = False
    remote: bool = False
    egress: bool = False
    mandate_ok: bool = False
    destructive: bool = False
    result_label: ResultLabel = "trusted"
    kind: ToolKind = "generic"
    sql_arg: str | None = None

    @property
    def pin(self) -> str:
        """sha256 of the parts a model sees and relies on: the description and the argument schema."""
        return sha256_hex(canonical_json({"description": self.description, "schema": self.schema}))


def _spec(name: str, raw: Mapping[str, Any]) -> ToolSpec:
    if not isinstance(raw, Mapping):
        raise ManifestError(f"tool {name!r}: entry must be a mapping")
    missing = [key for key in _REQUIRED if key not in raw]
    if missing:
        raise ManifestError(f"tool {name!r}: missing {', '.join(missing)}")
    unknown = set(raw) - set(_REQUIRED) - set(_OPTIONAL)
    if unknown:
        raise ManifestError(f"tool {name!r}: unknown field(s) {', '.join(sorted(unknown))}")
    for key in ("read_only", "state_changing", "reversible", *_FLAGS):
        if key in raw and not isinstance(raw[key], bool):
            raise ManifestError(f"tool {name!r}: {key} must be true or false")
    if raw["read_only"] == raw["state_changing"]:
        raise ManifestError(f"tool {name!r}: exactly one of read_only and state_changing must be true")
    if raw.get("destructive") and not raw["state_changing"]:
        raise ManifestError(f"tool {name!r}: a destructive tool must be state_changing")
    label = raw.get("result_label", "trusted")
    if label not in get_args(ResultLabel):
        raise ManifestError(f"tool {name!r}: result_label must be one of {', '.join(get_args(ResultLabel))}")
    kind = raw.get("kind", "generic")
    if kind not in get_args(ToolKind):
        raise ManifestError(f"tool {name!r}: kind must be one of {', '.join(get_args(ToolKind))}")
    if not isinstance(raw["description"], str) or not raw["description"].strip():
        raise ManifestError(f"tool {name!r}: description must be a non-empty string")
    schema = raw["schema"]
    try:
        check_schema(schema)
    except SchemaError as exc:
        raise ManifestError(f"tool {name!r}: {exc}") from exc
    if schema.get("type") != "object":
        raise ManifestError(f"tool {name!r}: the schema must describe an object")
    sql_arg = raw.get("sql_arg")
    if sql_arg is not None and sql_arg not in (schema.get("properties") or {}):
        raise ManifestError(f"tool {name!r}: sql_arg {sql_arg!r} is not a property of the schema")
    return ToolSpec(
        name=name,
        description=raw["description"],
        read_only=raw["read_only"],
        state_changing=raw["state_changing"],
        reversible=raw["reversible"],
        schema=schema,
        sensitive=raw.get("sensitive", False),
        remote=raw.get("remote", False),
        egress=raw.get("egress", False),
        mandate_ok=raw.get("mandate_ok", False),
        destructive=raw.get("destructive", False),
        result_label=label,
        kind=kind,
        sql_arg=sql_arg,
    )


PinState = Literal["ok", "changed", "missing"]
_DOCUMENT_KEYS = frozenset({"draft", "tools", "version"})


class Manifest:
    """All known tools plus the pins a human approved.

    A tool whose definition changed since its pin is denied (a possible attack). A tool that was never pinned is
    waiting for review (Amendment A1). A whole manifest can be a draft, which the gate only loads in observe mode.
    """

    def __init__(self, tools: Mapping[str, ToolSpec], pins: Mapping[str, str], draft: bool = False) -> None:
        self._tools = dict(tools)
        self._pins = dict(pins)
        self.draft = draft

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, Mapping[str, Any]],
        pins: Mapping[str, str] | None = None,
        draft: bool = False,
    ) -> Manifest:
        """Build from plain data (for example parsed YAML). With no pins, the current definitions are pinned."""
        if not isinstance(data, Mapping) or not data:
            raise ManifestError("the manifest must list at least one tool")
        tools = {name: _spec(name, raw) for name, raw in data.items()}
        return cls(tools, pins if pins is not None else {name: spec.pin for name, spec in tools.items()}, draft)

    @classmethod
    def from_document(cls, document: Mapping[str, Any], pins: Mapping[str, str] | None = None) -> Manifest:
        """A manifest file: {"draft": bool, "tools": {...}}."""
        if not isinstance(document, Mapping) or "tools" not in document:
            raise ManifestError("a manifest document must have a 'tools' section")
        unknown = set(document) - _DOCUMENT_KEYS
        if unknown:
            raise ManifestError(f"unknown manifest key(s): {', '.join(sorted(unknown))}")
        draft = document.get("draft", False)
        if not isinstance(draft, bool):
            raise ManifestError("'draft' must be true or false")
        return cls.from_mapping(document["tools"], pins=pins, draft=draft)

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def pin_of(self, name: str) -> str:
        return self._tools[name].pin

    def pin_state(self, name: str) -> PinState:
        spec = self._tools.get(name)
        pinned = self._pins.get(name)
        if spec is None or pinned is None:
            return "missing"
        return "ok" if pinned == spec.pin else "changed"

    def pin_ok(self, name: str) -> bool:
        return self.pin_state(name) == "ok"

    @property
    def pins(self) -> dict[str, str]:
        return dict(self._pins)

    @property
    def names(self) -> list[str]:
        return sorted(self._tools)
