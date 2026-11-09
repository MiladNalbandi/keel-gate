# Protect an app that uses OpenAI

> **Status: planned.** This page is written on Day 3. The outline below shows what it will cover.

Use the same gate with OpenAI `tool_calls`.

## What this page will cover

- Wrap your tool executor with `gate.run_openai_call(call, session)`.
- Return blocked calls as a tool message with the error text.
- Using the OpenAI Agents SDK `needsApproval` together with keel-gate.

Related: [Claude API apps](protect-claude-api-app.md)
