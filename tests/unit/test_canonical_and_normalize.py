"""AC-006, AC-007: one fingerprint for one logical call, whatever framework sent it."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from keel_gate.domain.canonical import call_hash, canonical_json
from keel_gate.domain.models import ToolCall
from keel_gate.normalize import (
    NormalizeError,
    from_claude_code_hook,
    from_claude_tool_use,
    from_mcp_call,
    from_openai_tool_call,
)

REFUND_ARGS = {"order": "1042", "amount": "500.00"}


def test_ac_007_canonical_json_sorts_keys_and_has_no_spaces() -> None:
    text = canonical_json({"b": 1, "a": {"y": "é", "x": [1, 2]}})

    assert text == '{"a":{"x":[1,2],"y":"é"},"b":1}'


def test_ac_007_call_hash_is_sha256_of_canonical_tool_and_args() -> None:
    expected = hashlib.sha256('{"args":{"a":1,"b":"é"},"tool":"x"}'.encode()).hexdigest()

    assert call_hash("x", {"b": "é", "a": 1}) == expected


def test_ac_007_any_change_to_args_changes_the_hash() -> None:
    first = call_hash("payments.refund", REFUND_ARGS)

    second = call_hash("payments.refund", {**REFUND_ARGS, "amount": "5000.00"})

    assert first != second


def test_ac_007_nan_cannot_be_hashed() -> None:
    with pytest.raises(ValueError, match="canonical"):
        call_hash("x", {"n": float("nan")})


def test_ac_007_tool_call_exposes_its_hash() -> None:
    call = ToolCall(tool="payments.refund", args=REFUND_ARGS)

    assert call.call_hash == call_hash("payments.refund", REFUND_ARGS)


def test_ac_006_refund_has_one_hash_from_every_framework() -> None:
    claude = from_claude_tool_use(
        {"type": "tool_use", "id": "toolu_1", "name": "payments__refund", "input": REFUND_ARGS}
    )
    openai = from_openai_tool_call(
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "payments__refund", "arguments": json.dumps(REFUND_ARGS)},
        }
    )
    mcp = from_mcp_call({"name": "refund", "arguments": REFUND_ARGS}, server="payments")
    hook = from_claude_code_hook({"tool_name": "mcp__payments__refund", "tool_input": REFUND_ARGS})

    hashes = {claude.call_hash, openai.call_hash, mcp.call_hash, hook.call_hash}

    assert hashes == {call_hash("payments.refund", REFUND_ARGS)}


def test_ac_006_shell_call_from_claude_code_matches_the_api_shape() -> None:
    hook = from_claude_code_hook(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la", "description": "List files", "timeout": 5000},
        }
    )
    api = from_claude_tool_use({"type": "tool_use", "id": "t", "name": "shell", "input": {"command": "ls -la"}})

    assert (hook.tool, hook.call_hash) == ("shell", api.call_hash)


@pytest.mark.parametrize(
    ("hook_tool", "expected"),
    [
        ("Read", "read_file"),
        ("Edit", "edit_file"),
        ("Write", "write_file"),
        ("WebFetch", "web.fetch"),
    ],
)
def test_ac_006_claude_code_tool_names_map_to_manifest_names(hook_tool: str, expected: str) -> None:
    call = from_claude_code_hook({"tool_name": hook_tool, "tool_input": {"file_path": "a.txt"}})

    assert call.tool == expected


def test_ac_006_claude_code_file_path_becomes_path() -> None:
    call = from_claude_code_hook({"tool_name": "Read", "tool_input": {"file_path": "src/cart.py"}})

    assert call.args == {"path": "src/cart.py"}


def test_ac_006_openai_arguments_that_are_not_json_are_rejected() -> None:
    with pytest.raises(NormalizeError):
        from_openai_tool_call({"id": "c", "type": "function", "function": {"name": "x", "arguments": "{oops"}})


def test_ac_006_hook_payload_without_tool_name_is_rejected() -> None:
    with pytest.raises(NormalizeError):
        from_claude_code_hook({"tool_input": {}})


def test_ac_006_missing_arguments_become_an_empty_object() -> None:
    call = from_mcp_call({"name": "status"}, server="ops")

    assert (call.tool, dict(call.args)) == ("ops.status", {})


def test_ac_006_empty_openai_arguments_become_an_empty_object() -> None:
    call = from_openai_tool_call({"id": "c", "type": "function", "function": {"name": "ping", "arguments": ""}})

    assert dict(call.args) == {}


@pytest.mark.parametrize(
    "payload",
    [
        {"id": "c", "type": "function"},
        {"id": "c", "type": "function", "function": {"name": "x", "arguments": "[1, 2]"}},
    ],
)
def test_ac_006_malformed_openai_calls_are_rejected(payload: dict[str, Any]) -> None:
    with pytest.raises(NormalizeError):
        from_openai_tool_call(payload)


def test_ac_006_unprefixed_names_stay_as_they_are() -> None:
    call = from_claude_tool_use({"type": "tool_use", "id": "t", "name": "read_file", "input": {"path": "a"}})

    assert call.tool == "read_file"
