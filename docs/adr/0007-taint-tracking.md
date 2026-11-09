# ADR 0007 — Session taint tracking for untrusted input and secrets

* **Status:** Accepted
* **Date:** 2026-11-09

## Context

Prompt injection works because text from a web page, email, ticket, or issue ends up steering a tool call. The GitHub MCP
and Supabase MCP leaks are examples. Full data-flow tracking (Google DeepMind's CaMeL tags every value with its origin and
uses a separate, tool-less LLM) is strong, but it needs control of the agent's planner, which a harness does not have.

## Decision

Use **session-level taint**, a simpler form that a harness can enforce:

- Each tool in the manifest labels its *results*: `trusted`, `untrusted`, or `secret`. Adapters report the label after each
  run (or `POST /v1/results`).
- After any `untrusted` result, the session is **untrusted**: egress tools and state-changing tools go up one step
  (allow → ask) (AC-061).
- After any `secret` result, the session is **secret-tainted**: every egress call is denied (AC-062).
- Taint never goes down inside a session. Only a human can clear it, through a new session.
- Tool result text is never parsed for instructions or approvals (AC-063).

## Consequences

- **Pros**
  - It blocks the classic "read untrusted, then leak or act" chain without changing the agent.
  - It is simple to explain and to test.
- **Cons**
  - It is coarser than CaMeL: once a session is tainted, more actions need a human. Mitigated by mandates and by splitting
    work into separate sessions (for example, research in one session, actions in another), which is also
    the "plan-then-execute" pattern.
