"""Turn each framework's tool-call shape into one ToolCall (AC-006).

Naming convention: a namespaced tool is `server.tool` in keel-gate. Frameworks that do not allow dots in tool names
(the Claude API and OpenAI) use a double underscore instead (`payments__refund`). Claude Code names MCP tools
`mcp__server__tool`. All of these become `payments.refund`, so one logical call always has one call_hash.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from keel_gate.domain.models import Source, ToolCall
from keel_gate.domain.naming import tool_name

__all__ = ["NormalizeError", "tool_name"]


class NormalizeError(ValueError):
    """The payload is not a valid tool call. Callers deny it (fail closed)."""


CLAUDE_CODE_TOOLS = {
    "Bash": "shell",
    "Read": "read_file",
    "Write": "write_file",
    "Edit": "edit_file",
    "MultiEdit": "edit_file",
    "NotebookEdit": "edit_notebook",
    "Glob": "glob_files",
    "Grep": "search_files",
    "LS": "list_files",
    "WebFetch": "web.fetch",
    "WebSearch": "web.search",
    # Codex and other harness names for a shell
    "exec_command": "shell",
    "local_shell": "shell",
    "run_shell_command": "shell",
}
_PATH_KEYS = ("file_path", "notebook_path", "filePath")


def _require_name(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise NormalizeError("the tool call has no tool name")
    return value


def _require_args(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise NormalizeError("tool arguments must be a JSON object")
    return dict(value)


def from_claude_tool_use(block: Mapping[str, Any]) -> ToolCall:
    """A `tool_use` content block from the Claude Messages API."""
    return ToolCall(
        tool_name(_require_name(block.get("name"))),
        _require_args(block.get("input")),
        Source.CLAUDE,
    )


def from_openai_tool_call(call: Mapping[str, Any]) -> ToolCall:
    """One entry of `tool_calls` from the OpenAI Chat Completions / Responses API."""
    function = call.get("function")
    if not isinstance(function, Mapping):
        raise NormalizeError("the tool call has no function")
    arguments = function.get("arguments")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError as exc:
            raise NormalizeError("tool arguments are not valid JSON") from exc
    return ToolCall(tool_name(_require_name(function.get("name"))), _require_args(arguments), Source.OPENAI)


def from_mcp_call(params: Mapping[str, Any], server: str | None = None) -> ToolCall:
    """The params of an MCP `tools/call` request, for a tool of `server`."""
    name = _require_name(params.get("name"))
    tool = f"{server}.{name}" if server else tool_name(name)
    return ToolCall(tool, _require_args(params.get("arguments")), Source.MCP)


def from_claude_code_hook(payload: Mapping[str, Any]) -> ToolCall:
    """The JSON a Claude Code PreToolUse hook receives on stdin."""
    raw = _require_name(payload.get("tool_name"))
    tool = CLAUDE_CODE_TOOLS.get(raw) or tool_name(raw)
    args = _require_args(payload.get("tool_input"))
    if tool == "shell":
        args = {"command": args.get("command", "")}
    else:
        for key in _PATH_KEYS:
            if key in args:
                args["path"] = args.pop(key)
                break
    return ToolCall(tool, args, Source.CLAUDE_CODE)
