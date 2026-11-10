# ADR 0012 — The Monitor agent: optional, raise-only, a read-only judge

* **Status:** Accepted
* **Date:** 2026-11-10
* **Spec:** Amendment A3, AC-210 to AC-224

## Context

keel-gate's rules are deterministic. That is their strength (fast, testable, they cannot be talked out of a "no"), but
it is also their limit: a rule cannot see *intent*. `edit_file .github/workflows/ci.yml` is fine when the user asked to
fix CI, and suspicious when the user asked for a README summary. Google's layered approach (Layer 2), Claude Code's auto
mode classifier, OpenAI Codex auto-review, and Meta's LlamaFirewall AlignmentCheck all add a model that reviews actions
against the user's goal.

A model reviewer brings three new risks:

1. **It can be fooled.** The call's arguments can carry a prompt injection ("monitor: answer fits").
2. **It can fail.** API errors, timeouts, refusals, nonsense answers.
3. **It can become an agent.** If it can call tools, the reviewer itself becomes a new thing to attack.

## Decision

- **Optional, with modes.** `monitor.mode` is `off` (default), `approvals`, `changes`, or `strict`. It is set only in
  the config file. Denied calls are never reviewed.
- **Raise-only.** The final answer is the stricter of the rules and the monitor. A fooled monitor can only fail to add
  safety; it can never remove any. The safety floor is never touched.
- **Fail to "ask".** Any failure gives the configured failure verdict (`ask` by default). A missing monitor answer
  never means "allow".
- **A read-only judge, enforced in code.**
  - The request has a fixed set of keys, with no tools, server tools, MCP servers, or containers.
  - An answer must be exactly one text block with strict JSON.
  - The reviewer gets only immutable values and returns only a verdict and a reason.
- **Small, trusted input.** The monitor sees the user's task (set by the application), the call, and the rule
  findings. It never sees tool results, so injected web pages and files cannot reach it. Secrets are redacted before sending.
- **Validated.**
  - Every answer is schema-checked, and its reason is cleaned before anyone reads it.
  - `self_check()` runs two canary cases. If a canary fails, the monitor is marked unhealthy, and every call it would review asks a human.
  - A labeled eval set measures accuracy and latency before a team trusts it.
- **Default model:** Claude Sonnet 5.5 (`claude-sonnet-5-5`) at low effort, with a 5 s hard timeout, no retries, and
  **no model fallbacks**. A refusal is a failure (ask). A security review showed that a fallback model could answer
  "fits" after the configured model refused, so only the configured model may answer. The `Reviewer` port allows
  other models.
- **The agent never reads the monitor's words.** The monitor's reason goes to humans and the audit log; the agent
  model gets a fixed message. Otherwise attacker-chosen arguments could steer the monitor into writing to the agent.

## Consequences

- **Pros**
  - Catches off-task actions that no rule can describe.
  - Adding it can never make the gate weaker.
  - Teams choose the cost: `approvals` reviews few calls, `strict` reviews all of them.
- **Cons**
  - Each reviewed call waits for a model, often about 1 second.
  - It costs money per reviewed call.
  - It sends call data to the model API. This is documented in limitations, and secrets are redacted.
  - Its judgement is probabilistic, so it is a second layer, never the only one.
