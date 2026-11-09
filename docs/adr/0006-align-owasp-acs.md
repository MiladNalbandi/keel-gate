# ADR 0006 — Use the OWASP Agent Control Standard decision shape

* **Status:** Accepted
* **Date:** 2026-11-09

## Context

We need a decision format for adapters, the API, and the audit log. We could invent our own (`allow`/`block`/`confirm`),
but the OWASP Agent Control Standard v0.1 (Sep 2026) already defines hooks such as `toolCallRequest` and the policy answers
`allow`, `deny`, `modify`, `ask`, `defer`. Following a public standard makes keel-gate easier to adopt and easier for judges to trust.

## Decision

- `Verdict` = `allow | ask | deny | modify | defer`.
  - In this version keel-gate produces `allow`, `ask`, and `deny`.
  - `modify` (for example, capping an amount or redacting an argument) and `defer` (pause and resume later) are in the model
    and the API so that adapters handle them, but no built-in rule emits them yet.
- A `Decision` carries `verdict`, `tier`, `reasons`, `rule_ids`, `call_hash`, and `message_for_model`.
- Adapters map verdicts to each framework, for example Agent SDK `permissionDecision` allow / deny / ask / defer.

## Consequences

- **Pros**
  - A shared vocabulary with the wider ecosystem; simpler future integrations.
- **Cons**
  - The standard is v0.1 and may change. Mitigated by keeping the mapping in one module (`domain/models.py`) and pinning
    the version we follow in the docs.
