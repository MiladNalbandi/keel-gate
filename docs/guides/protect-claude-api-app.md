# Protect an app that uses the Claude API

> **Status: planned.** This page is written on Day 3. The outline below shows what it will cover.

Put keel-gate inside your own tool loop, so Claude's `tool_use` blocks are decided before they run.

## What this page will cover

- The manual tool loop: `gate.run_tool_use(block, session)` returns the `tool_result`.
- Blocked calls go back as `is_error: true` with the reason, so Claude can stop or ask.
- Reporting result labels (trusted / untrusted / secret) for taint tracking.
- Using the Claude Agent SDK instead: an async `PreToolUse` hook.

Related: [OpenAI apps](protect-openai-app.md) · [decisions](../reference/decisions.md)
