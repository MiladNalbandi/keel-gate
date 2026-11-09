# ADR 0010 — Draft manifests from existing tool definitions

* **Status:** Accepted
* **Date:** 2026-11-09
* **Spec:** Amendment A1, AC-185 to AC-188

## Context

keel-gate denies tools that are not in the manifest (AC-003). An existing system may have dozens of tools, and writing
each manifest entry by hand is the "huge change" that blocks adoption. But those tools are already described
somewhere:

- MCP servers return `tools/list`, with an `inputSchema` and optional `annotations` (`readOnlyHint`, `destructiveHint`, `openWorldHint`).
- Claude API apps pass tool definitions with `input_schema`.
- OpenAI apps pass function tools with `parameters`.

Guessing risk from tool names (for example "delete_*" means destructive) is tempting, but names can lie or mislead.

## Decision

- `draft_manifest()` (and `keel-gate init` / `POST /v1/tools`) converts these definitions into manifest entries:
  - MCP hints map directly: `readOnlyHint` → read only; `destructiveHint` → destructive; `openWorldHint` → remote + egress.
  - A tool with **no hints** is drafted as state-changing and not reversible, so calls to it **ask** (never allow, never guess).
  - Schema keywords outside our subset are removed, and each removal is listed as a review note.
- A draft file is marked `draft: true`.
  - The gate loads a draft only in observe mode.
  - In enforce mode it refuses to start until a human reviews the draft and removes the marker (or pins the tool in the UI).
- No guessing from names.

## Consequences

- **Pros**
  - Adding keel-gate to a system with 50 tools takes one command plus a review, not 50 hand-written entries.
  - Safe defaults: unknown risk becomes "ask", and an unreviewed draft can never be enforced by accident.
- **Cons**
  - Tools without MCP hints start as "ask", which is noisy until reviewed. Mitigated by observe mode (ADR 0009) and
    one-click edits in the policy manager (ADR 0011).
  - MCP hints come from the tool server and are only hints. Mitigated by human review and pinning (AC-091).
