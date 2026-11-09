# ADR 0009 — Observe mode with a safety floor

* **Status:** Accepted
* **Date:** 2026-11-09
* **Spec:** Amendment A1, AC-180 to AC-184

## Context

Teams that already run agents cannot switch on a gate that may block real work on day one. If the first week brings
false "ask" prompts and blocked tools, people disable the gate, and then it protects nothing. Many security tools solve
this with a monitor-only or "shadow" mode (keel v2's Supervisor also has a shadow mode).

A pure log-only mode is tempting: allow everything and just record. But that means the most dangerous actions run
during adoption, which is exactly when nobody has tuned the rules yet.

## Decision

- Add `mode: enforce | observe` to the gate's config file. The default is `enforce`.
- In `observe` mode a **safety floor** still denies:
  - every T3 deny from a content rule (`rm_rf_dangerous`, `sql_drop`, `git_force_protected`, `remote_destructive`, `destructive_tool`, protected paths)
  - `tool_pin_changed` (a possible attack)
  - `gate_error` (fail closed)
- Everything else that would be `ask` or `deny` becomes `allow`. The Decision keeps `observed_verdict`, and the
  report shows "would have asked / denied".
- Unknown tools are allowed in observe mode and listed, so teams see which tools still need a manifest entry.
- The mode is read only from the config file and is part of the policy hash. No API endpoint or agent can change it.

## Consequences

- **Pros**
  - Adoption without breaking work. Teams tune rules on real traffic, then switch to enforce with evidence.
  - The worst incidents (Replit, PocketOS, Antigravity) are still blocked during the trial.
- **Cons**
  - T2 actions such as refunds and emails run without a human while in observe mode. Mitigated by a loud banner in the
    console and report, a reminder in every log line, and the advice to keep observe periods short.
