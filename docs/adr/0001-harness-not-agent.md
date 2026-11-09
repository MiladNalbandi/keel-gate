# ADR 0001 — Build a harness around tool calls, not a safer agent

* **Status:** Accepted
* **Date:** 2026-11-09

## Context

The challenge asks how to stop agents from taking unauthorized, irreversible actions. Two broad options:

1. Make the **agent** safer (better prompts, a fine-tuned model, an LLM judge that reviews each step).
2. Put a **harness** between the model and its tools, so no tool runs without a decision made outside the model.

Option 1 is tempting because it needs no new infrastructure. But research shows it is not enough on its own:
the best of 17 frontier models abstains correctly only 59.5% of the time (AgentAbstain). Anthropic's auto-mode classifier
still misses about 17% of overeager actions, and prompt instructions such as a "code freeze" did not stop the Replit agent.
Google, Anthropic, and OpenAI all place a deterministic policy layer outside the model.

## Decision

Build keel-gate as a **harness on top of LLM tool calling**:

- one pure `decide()` function
- adapters for the Claude API, OpenAI, the Agent SDK, Claude Code hooks, and MCP
- a Gate Service for remote use

It ships as its own repo, as a Keel feature. Keel v2 can import it later.

## Consequences

- **Pros**
  - It works with any model and any framework; the model can be wrong and the gate still holds.
  - Its behavior can be tested and proven (deterministic), which suits judges and auditors.
- **Cons**
  - It cannot judge *intent* inside an allowed action. Mitigated by tiers, mandates, and optional detectors that may only raise risk.
  - Every framework needs an adapter. Mitigated by a small, shared `ToolCall` model.
