# ADR 0004 — A hash-chained JSONL audit log

* **Status:** Accepted
* **Date:** 2026-11-09

## Context

After an incident, the first question is "what exactly did the agent do, and who allowed it?" The Replit agent even claimed
a rollback was impossible. The log must be the ground truth, and someone with file access should not be able to quietly
edit it. Options: plain DB rows (keel v2 today), a remote log service, or an append-only file with a hash chain.

## Decision

- Write one JSON line per decision to `audit.jsonl`. Each line has `prev_hash` and
  `entry_hash = sha256(canonical(line without entry_hash))`. The first line uses 64 zeros as `prev_hash`.
- `keel-gate audit verify` (and `GET /v1/audit/verify`) recomputes the chain and reports the first bad line.
- Arguments are **redacted** before writing: known secret keys, vault values, and token-like strings become `[redacted]` (AC-131).
- One background writer appends lines, so `decide()` never waits on disk, and lines stay in order.
- Stretch: export to OTel/OCSF, and sign approval records (ES256) on top of the chain.

## Consequences

- **Pros**
  - Tampering, deletion, and reordering are detectable with a few lines of code; anyone can check it.
  - It is plain text, easy to read, and powers the Agent History report.
- **Cons**
  - A hash chain shows tampering but does not prevent it, and someone could rewrite the whole chain. Mitigated by
    publishing the latest `entry_hash` (for example in the report and to the approver) and by optional signatures (stretch).
