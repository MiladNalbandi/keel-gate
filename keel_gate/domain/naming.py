"""Tool naming: one name per tool, whatever framework sends it.

A namespaced tool is `server.tool`. The Claude API and OpenAI do not allow dots in tool names, so they use
`server__tool`; Claude Code names MCP tools `mcp__server__tool`. All of these become `server.tool`.
"""

from __future__ import annotations


def tool_name(raw: str) -> str:
    if raw.startswith("mcp__"):
        parts = raw.split("__", 2)
        if len(parts) == 3 and parts[1] and parts[2]:
            return f"{parts[1]}.{parts[2]}"
    if "__" in raw:
        server, tool = raw.split("__", 1)
        if server and tool:
            return f"{server}.{tool}"
    return raw
