# ADR 0002 — Fail closed everywhere

* **Status:** Accepted
* **Date:** 2026-11-09

## Context

Any part of the gate can fail: a parser bug, a broken policy file, a timeout, an unreachable Gate Service.
The easy default is "fail open": if the check breaks, let the call through so work is not blocked.
Real systems show the risk:

- Claude Code `command`/`http` hooks do **not** block on failure by default.
- A failed `mkdir` that nobody checked led Gemini CLI to destroy files.
- A Tally bot in our own platform repo nearly sent every group message to the model because of a fail-open fallback.

## Decision

On any error, timeout, or unknown input the verdict is **deny**:

- `GateService.decide()` wraps the pipeline: any exception, or going past the time budget, gives `deny` with reason
  `gate error: <kind>`. The error is logged without secrets.
- Unknown tools, invalid arguments, and unparseable shell text never give `allow` (AC-003, AC-005, AC-014).
- Remote adapters deny when the Gate Service is unreachable. The Claude Code cloud hook uses `onFailure: "block"` (AC-152).
- An invalid policy stops the gate from starting (AC-025). A policy whose hash changed denies every non-read call (AC-031).
- `ruff` rule `BLE` forbids blind `except Exception` that swallows errors without a deny.

## Consequences

- **Pros**
  - A bug in the gate cannot become an open door.
  - Behavior under failure is simple to explain and to test.
- **Cons**
  - Gate bugs block real work. Mitigated by read-only calls staying cheap and safe, by a strong test suite, and by clear
    deny reasons, so problems are visible fast.
