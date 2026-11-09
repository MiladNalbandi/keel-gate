# Protect MCP tools

> **Status: planned.** This page is written on Day 3. The outline below shows what it will cover.

Run keel-gate as an MCP proxy in front of your real MCP servers. Works with Claude Desktop, Claude Code, and claude.ai custom connectors.

## What this page will cover

- Local proxy (stdio) and remote proxy (Streamable HTTP over HTTPS with OAuth).
- Only manifest tools are listed; every `tools/call` goes through the gate.
- The gate holds the downstream credentials (no token passthrough).
- Tool pinning: what happens when a server changes a tool description.

Related: [tool manifest](../reference/tool-manifest.md)
