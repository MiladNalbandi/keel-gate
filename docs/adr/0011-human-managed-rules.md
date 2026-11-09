# ADR 0011 — Humans manage rules and tools in the UI and CLI, fast and versioned

* **Status:** Accepted
* **Date:** 2026-11-09
* **Spec:** Amendment A2, AC-190 to AC-200
* **Changes:** the "git review only" rule in Spec 001's authorization rules (still available as a setting)

## Context

The first design allowed policy changes only through git review, so that an agent can never change its own rules.
That is safe but slow: blocking a new risk, allowing a safe command like `npm test`, or adding a tool should take
seconds. The project owner asked for rules and tools that are easy to add, manage, and remove, and super fast.

The real requirement behind "git only" is **separation**: agents must never change policy, and every change must be
attributable and reversible. A UI can meet that if it is human-only, re-confirmed, versioned, and audited.

## Decision

**Who and how**
- A **policy-admin** role can add, edit, enable, disable, and remove custom rules and tools from the UI, the CLI
  (`keel-gate rule add|list|disable|remove`, `keel-gate tool import|pin|remove`), or the YAML files.
- Changes need a human session, a **step-up** re-confirmation (password or passkey, valid 5 minutes), and a CSRF token.
  Agent keys and approver-only sessions get 403.

**Guardrails on what a rule can do**
- A custom allow can turn ask into allow, but it can never override the safety floor or protected paths.
- Every change creates a numbered version with an audit entry (who, when, before, after). Rollback takes one step.
- Teams that need code review set `policy_changes: git`. The UI then becomes read-only and shows the exact file change to make.

**Storage**
- Custom rules live in `policies/custom.yaml`, written by the gate, readable, and diffable in git.
- Version history lives in SQLite. The gate re-pins the policy hash after a human change.

**Speed**
- Rules are compiled once per change into an immutable index: a dict by exact tool name, plus a short list of glob rules.
- The new index replaces the old one in one atomic step. `decide()` reads the current index and never takes a lock.
- A change made through the UI or CLI applies to the next decision. A hand edit of the file is picked up by a
  cheap mtime check, at most once per 0.5 s (well inside the 1-second promise).
- Target: p99 below 1 ms with 1,000 custom rules (AC-200), measured by the benchmark.

## Consequences

- **Pros**
  - Adding or removing a block takes seconds. Every change is safe to try, because rollback is one step.
  - It keeps the core security property: agents can never change rules, and every change is visible.
- **Cons**
  - A stolen admin session could weaken rules. Mitigated by step-up, a separate role from approvers, the audit trail,
    the floor that no custom rule can lower, and the optional git-only setting.
