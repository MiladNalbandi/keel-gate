# ADR 0008 — Standing mandates with hard limits instead of "always allow"

* **Status:** Accepted
* **Date:** 2026-11-09

## Context

If every refund needs a human click, people stop reading and click "yes" (about 93% acceptance per Anthropic). "Allow
always" fixes the speed problem but removes the limit. Payment networks solved this with **mandates**: Google AP2 open
payment mandates and Stripe Shared Payment Tokens carry a per-transaction cap, a total budget, allowed payees, a use count,
and an expiry.

## Decision

- A **mandate** is created by a human (`POST /v1/mandates` or the Mandates page) for one tool. It holds:
  `per_call_cap`, `budget`, `payees`, `max_uses`, and `expires_at` (at most 30 days).
- A call inside **every** limit is allowed, and the budget and uses go down in the same atomic SQL `UPDATE … WHERE`
  (AC-050, AC-052).
- A call outside any limit becomes `ask` (AC-051). Revoked or expired mandates allow nothing (AC-053).
- Mandates only cover T2 tools whose manifest marks them `mandate_ok`. T3 can never be covered by a mandate.
- Money values are decimals stored as strings, never floats.

## Consequences

- **Pros**
  - Routine actions are fast and still bounded; humans approve the *limit* once.
  - The budget stops "split payments under the cap" attacks.
- **Cons**
  - A wrong action inside the limits still happens. Mitigated by small default limits, the audit log, undo for reversible
    tools, and the breaker.
