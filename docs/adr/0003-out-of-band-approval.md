# ADR 0003 — Out-of-band, one-time approvals bound to the exact call

* **Status:** Accepted
* **Date:** 2026-11-09

## Context

Asking a human is the classic control, but weak approvals fail in known ways:

- **Self-approval:** the model sends back a token it saw, or text that says "APPROVED". keel v2 found this, which is why
  dangerous kinds need its Inbox.
- **Swap (TOCTOU):** the human approves action A, then action B runs.
- **Replay:** an old "yes" is reused.
- **Fatigue:** "Allow always" turns one approval into a standing grant. Users accept about 93% of prompts.
- **Unauthenticated state:** OpenAI's Agents SDK notes that serialized run state is not authenticated, so keep approval
  state server-side and consume it atomically.

## Decision

- An `ask` creates an approval with:
  - `call_hash` = sha256 of the canonical JSON `{tool, args}`
  - session, agent, and policy version
  - `expires_at` (default 300 s)
  - a short **binding code** shown both on the card and in the agent's message (like CIBA's `binding_message`)
- Approval state lives only on the gate side (SQLite). Using a token is one atomic
  `UPDATE … SET status='used' WHERE id=? AND status='approved' AND call_hash=? AND expires_at>?`.
- Only a **human session** can approve. Agent keys get 403. The approver must differ from the requester.
- First answer wins (409 after). An expiry ends as `expired` and the agent gets a clear deny.
- T2 and T3 never offer "always". Standing approval exists only as a **mandate** with hard limits (see ADR 0008).

Ported from keel v2 `mcp_confirm.py` (`Tokens`) and `approvals.py`, then hardened.

## Consequences

- **Pros**
  - An approval means exactly one call, once, by a real human.
  - It maps cleanly to standards (CIBA + RAR), so it could later be delivered through Auth0 or similar.
- **Cons**
  - Approvals add delay. Mitigated by mandates for routine, limited actions and by phone delivery.
