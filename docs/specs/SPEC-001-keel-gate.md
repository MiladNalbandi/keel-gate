# Spec 001 — keel-gate: an action firewall for LLM tool calls

* **Status:** Frozen (approved 2026-11-09)
* **Date:** 2026-11-09
* **Contract:** [`docs/api/openapi.yaml`](../api/openapi.yaml) (Gate Service). The library API is described in this spec.

## Goal

Stop AI agents from running **unauthorized or irreversible** tool calls. Every call goes through one fast, fail-closed
gate that decides **allow / ask a human / deny** before the tool runs.

## User stories

- As a **developer using a coding agent**, I want `rm -rf`, `DROP TABLE`, and force-pushes stopped before they run, so that one bad step
  cannot destroy my work.
- As a **company running a customer-support agent**, I want big refunds and unusual emails to wait for a human, and small refunds
  inside a limit to run on their own, so that customers get fast help and the company does not lose money.
- As an **approver**, I want to see exactly what the agent will do and why on my phone, and approve **only that one action**,
  so that my "yes" cannot be reused for something else.
- As a **security reviewer**, I want a tamper-evident log of every decision, so that I can prove what happened.
- As an **agent builder**, I want a blocked call to come back to the model as a clear tool error, so that the agent can stop
  or ask the user instead of crashing.

## Words used in this spec

| Word | Meaning |
|---|---|
| **Tool call** | One request from the model to run a tool: a name plus arguments. |
| **Verdict** | `allow`, `ask`, `deny`, `modify`, or `defer` (OWASP Agent Control Standard shape). |
| **Tier** | T0 read-only · T1 undoable · T2 hard to undo (needs a human) · T3 catastrophic (never by an agent). |
| **Session** | One agent run. It has an agent id, an optional customer (`on_behalf_of`), and taint flags. |
| **Taint** | A flag on a session after it reads untrusted data (web, email, ticket) or a secret. |
| **Mandate** | A standing approval with limits (amount cap, budget, payees, uses, expiry). |
| **Binding code** | A short code (for example `K7-42Q`) shown on the approval card and in the agent's message, so the human knows which request they approve. |

## Acceptance criteria

Each AC is observable and maps to at least one test. Test names start with the AC id (`test_ac_013_...`).

### A. Decisions and fail closed

```
AC-001 decide(call, session) returns a Decision with: verdict, tier, reasons (list), rule_ids (list), call_hash.
AC-002 When several rules match, the most restrictive verdict wins: deny > ask > allow.
AC-003 A tool that is not in the manifest is denied (reason "unknown tool").
AC-004 If any step of decide raises an error or passes its time budget, the verdict is deny (reason starts with "gate error").
AC-005 Arguments that do not match the tool's JSON schema are denied (reason "invalid arguments").
AC-006 The same logical call from Claude tool_use, OpenAI tool_calls, MCP tools/call, or Claude Code hook JSON gets the same call_hash.
AC-007 call_hash is sha256 of canonical JSON (sorted keys, no extra spaces, UTF-8) of {tool, args}; any change to args changes it.
```

### B. Shell commands (parsed, not string-matched)

```
AC-010 Compound commands (; && || | newline, subshells) are split; each part is decided; the overall verdict is the most restrictive.
AC-011 Wrappers are unwrapped and the inner command is decided: sh -c, bash -c, env, xargs, timeout, nice, nohup, sudo, npx, uvx.
AC-012 The real program is resolved: /bin/rm, /proc/self/root/usr/bin/rm, ./rm, and RM all count as rm.
AC-013 Command substitution $( ) or backticks, eval, and "decode then run" pipelines (base64 -d | sh) are at least ask; if the decoded text matches a T3 rule, deny.
AC-014 Text the parser cannot parse is at least ask (never allow).
AC-015 Argument-injection flags in otherwise safe tools are at least ask: find -exec/-execdir/-delete, fd -x, git -c, go test -exec, xargs with a shell.
```

### C. Tiers and built-in rules

```
AC-020 Read-only tools and read-only commands (ls, cat, grep, git status, git log, git diff) are allowed (T0).
AC-021 Recursive delete of /, ~, $HOME, a path outside the workspace, or a path built from an empty variable is denied (T3).
AC-022 git push --force / --force-with-lease / +refspec to a protected branch is denied (T3).
AC-023 SQL DROP, TRUNCATE, or DELETE/UPDATE without WHERE, through any client or tool, is denied (T3).
AC-024 Remote destructive API calls (HTTP DELETE to an infra host, or a tool whose manifest says remote+destructive) are denied (T3).
AC-025 Policy files are loaded at start; an invalid policy stops the gate from starting (fail closed).
```

### D. Self-protection and integrity

```
AC-030 Writes to protected paths are denied (T3): .claude/, .codex/, .cursor/, .vscode/, .mcp.json, .git/hooks/, .git/config,
       the policy folder, and the gate data folder. Matching ignores case and follows symlinks.
AC-031 If the policy hash at load differs from the pinned hash, every non-read call is denied until a human re-pins.
AC-032 Calls that try to turn off the gate or the sandbox (stop the gate process, set KEEL_GATE_OFF, edit hook settings) are denied.
```

### E. Human approval (ask)

```
AC-040 An ask verdict creates a pending approval with id, binding code, call_hash, requester, and expires_at (default 300 s).
AC-041 An approval lets exactly that call run once: a call with different args (different call_hash) is rejected.
AC-042 An approval token is single-use: a second use is rejected, also when the first run failed.
AC-043 An expired approval cannot be approved or used; it ends with status "expired" and the call does not run.
AC-044 The approver must be a human identity different from the requester; agent credentials cannot approve (HTTP 403).
AC-045 First answer wins: after approve or deny, more answers are rejected (HTTP 409).
AC-046 For T2 and T3 there is no "always allow"; an approval never becomes a standing grant.
AC-047 When an approval expires, the agent receives a deny with reason "approval timed out; a human was asked".
```

### F. Mandates (standing, limited approvals)

```
AC-050 A mandate with per-call cap, total budget, allowed payees, max uses, and expiry auto-allows a call inside every limit
       and lowers the remaining budget and uses in the same step.
AC-051 A call outside any limit of every matching mandate is ask (never a silent allow).
AC-052 Concurrent calls can never spend more than the budget or more than the uses (property test).
AC-053 A revoked or expired mandate allows nothing.
```

### G. Taint (untrusted input and secrets)

```
AC-060 A tool result from a source labeled untrusted (web fetch, email, ticket, issue, external MCP) marks the session untrusted.
AC-061 In an untrusted session, egress tools and state-changing tools go up one step: allow becomes ask; ask and deny stay.
AC-062 After a session reads a secret-labeled source, every egress call is denied.
AC-063 Text inside tool results can never approve, change policy, or lower a tier (an injected "APPROVED by admin" has no effect).
```

### H. Egress (network)

```
AC-070 Egress to a host not on the allow-list is denied; egress to private, loopback, link-local, or metadata addresses is denied.
AC-071 Hosts on the read-list allow GET/HEAD only; POST/PUT/PATCH/DELETE and uploads need the write-list.
AC-072 DNS exfiltration patterns are denied: ping/nslookup/dig/host/curl with a host built from $( ), backticks, or variables.
```

### I. Identity and credentials

```
AC-080 The acting principal (agent_id, on_behalf_of) comes from the session, never from tool arguments; a call that targets
       another customer's resource is denied.
AC-081 Tools run with credentials held by the gate vault; credential values never appear in tool results, the audit log,
       or messages to the model.
AC-082 Calls that target an environment marked protected (for example prod) are denied for agents.
```

### J. Tool manifest and pinning

```
AC-090 Every tool has a manifest entry: read_only, state_changing, reversible, sensitive, remote, egress, mandate_ok,
       result_label (trusted / untrusted / secret), and a JSON schema for its arguments.
AC-091 Each tool is pinned by sha256 of its schema plus description; if the pin changes, calls are denied until a human re-pins.
```

### K. Circuit breaker and kill switch

```
AC-100 After 3 denials in a row, or 20 denials in one session, the session trips: every non-read call is ask (reason "breaker").
AC-101 When the kill switch is on, every non-read call is denied.
```

### L. Messages, claims, and checks after actions

```
AC-110 An outgoing message tool (send_message, send_email, reply) that promises a refund, discount, price, or policy exception
       without a policy reference is ask.
AC-111 If the agent's final text claims success ("done", "deleted", "refunded") for a call that was denied or never ran,
       the report marks it as a false claim.
AC-112 When a tool declares a postcheck and the check fails, later state-changing calls in the session are denied until
       a human clears the session.
```

### M. Undo

```
AC-120 For T1 calls with an undo handler, the gate saves before/after state; undo(session) restores it, newest first.
```

### N. Audit log

```
AC-130 Every decision adds one JSONL line with prev_hash and entry_hash; verify() passes on an untouched log and fails if any
       line is changed, removed, added, or moved.
AC-131 Audit lines never contain secret values or approval tokens (redaction test with planted secrets).
```

### O. Adapters

```
AC-140 Claude API adapter: a denied tool_use becomes a tool_result with is_error=true and the reason; an allowed one runs and
       returns the tool output.
AC-141 OpenAI adapter: the same behavior for tool_calls (a tool message with the error text).
AC-142 Claude Code hook: allow → exit 0; deny → exit 2 with the reason on stderr; ask → exit 2 with the binding code; any hook
       error → exit 2.
AC-143 Agent SDK adapter returns permissionDecision allow / deny / ask; a timeout returns deny.
AC-144 MCP proxy: tools/list shows only manifest tools that are not always-denied; tools/call goes through decide.
```

### P. Gate Service (HTTP)

```
AC-150 POST /v1/decide without a valid agent key returns 401 and reveals nothing.
AC-151 Approve and deny need a human session and a CSRF token; an agent key returns 403.
AC-152 When the Gate Service cannot be reached, remote adapters deny (fail closed).
AC-153 Error responses never include stack traces, file paths, SQL, or secrets.
AC-154 GET /v1/audit/verify returns {ok: true|false, entries, first_bad_line}.
```

### Q. Speed and report

```
AC-160 decide() has p99 below 1 ms over 10,000 mixed calls on a developer laptop (tool run time and human wait not included).
AC-170 The report command writes one HTML file with the timeline: time, agent, tool, verdict, tier, reason, rule, taint marks,
       false-claim marks, and the hash-chain status.
```

## Endpoints

The full schemas live in [`docs/api/openapi.yaml`](../api/openapi.yaml).

| Method | Path | Who | Success | Errors |
|---|---|---|---|---|
| POST | `/v1/decide` | agent key | 200 `Decision` | 401, 422, 429 |
| POST | `/v1/results` | agent key | 204 | 401, 422 |
| GET | `/v1/approvals?status=pending` | human session | 200 `[Approval]` | 401 |
| POST | `/v1/approvals/{id}/approve` | human session + CSRF | 200 `Approval` | 401, 403, 404, 409, 410 |
| POST | `/v1/approvals/{id}/deny` | human session + CSRF | 200 `Approval` | 401, 403, 404, 409 |
| GET | `/v1/mandates` | human session | 200 `[Mandate]` | 401 |
| POST | `/v1/mandates` | human session + CSRF | 201 `Mandate` | 401, 403, 422 |
| DELETE | `/v1/mandates/{id}` | human session + CSRF | 204 | 401, 403, 404 |
| GET | `/v1/audit` | human session | 200 `[AuditEntry]` | 401 |
| GET | `/v1/audit/verify` | human session | 200 `VerifyResult` | 401 |
| GET | `/healthz` | anyone | 200 | — |

## Validation rules

| Field | Required | Type | Rule |
|---|---|---|---|
| `tool` | yes | string | 1–200 chars, `^[A-Za-z0-9_.:/-]+$` |
| `args` | yes | object | JSON object, at most 64 KB when encoded; must match the tool's schema |
| `session_id` | yes | string | 1–100 chars, `^[A-Za-z0-9_-]+$` |
| `source` | no | enum | `claude`, `openai`, `mcp`, `claude_code`, `agent_sdk`, `raw` (default `raw`) |
| `result_label` | no | enum | `trusted`, `untrusted`, `secret` (for reporting a tool result back) |
| Mandate `per_call_cap` | yes | decimal | > 0, ≤ `budget` |
| Mandate `budget` | yes | decimal | > 0 |
| Mandate `max_uses` | yes | int | 1–10,000 |
| Mandate `expires_at` | yes | datetime | in the future, at most 30 days ahead |
| Mandate `payees` | yes | list[string] | 1–100 items |

Failure response: **422** with `{message, errors: {field: [text]}}`. Unknown fields are rejected (no mass assignment).

## Authorization rules

- **Agents** (agent key) may only call `/v1/decide` and report tool results. They may never approve, deny, create mandates, or read the audit log.
- **Humans** (approver session) may approve, deny, manage mandates, and read the audit log.
- An approver may not approve a request whose requester is their own agent identity (AC-044).
- Policy and manifest changes happen through git review, never through the API (no endpoint exists).

## Domain rules

- The most restrictive verdict always wins (AC-002).
- Tiers only go up inside one decision; nothing in a decision can lower a tier (AC-063).
- Time comes from an injected clock; expiry logic never reads the system time directly.
- Approval and mandate state lives on the gate side; nothing the model sends is trusted as approval.

## Edge cases

- Two approvals race for the same call → only one can consume it (AC-042, atomic).
- A mandate is used by two calls at the same moment → the budget never goes below zero (AC-052).
- An approval expires while the human is looking at the card → approve returns 410, and the agent gets a deny (AC-043, AC-047).
- The audit log file is deleted → verify reports `ok: false` and the gate denies state-changing calls until a human resets it.
- Very long or binary-looking arguments → limited to 64 KB, else 422.
- The shell parser hits a grammar it does not know → ask, never allow (AC-014).

## Security concerns

- **Prompt injection:** tool output is data only; taint raises tiers (AC-060–063).
- **Self-modification:** the agent edits its own config or policy (AC-030–032).
- **Replay / swap:** an approval is reused or applied to changed args (AC-041–042).
- **Approval fatigue:** too many prompts → mandates (AC-050) + the breaker (AC-100).
- **Credential theft:** the agent never holds keys (AC-081).
- **Exfiltration:** egress lists, DNS patterns, secret taint (AC-062, AC-070–072).
- **Repudiation:** the hash-chained audit log (AC-130).
- **Error leakage:** no internals in errors (AC-153).
- **Rate limiting:** `/v1/decide` is limited per agent key (default 50 calls per second); `/approve` is limited per human session.

## Out of scope (this iteration)

- Real payment, email, or cloud providers (the demo uses a mock world only).
- An OS-level sandbox (documented as a recommended extra layer; a Docker "agent box" is a stretch goal).
- LLM-based reviewers and detector plug-ins (stretch; they could only raise a tier).
- OTel/OCSF export and ES256-signed approval records (stretch).
- Editing policies in the UI (by design: policy changes go through git review).
- Multi-tenant hosting.

---

<!-- Once a test references this spec it is frozen. Add dated amendment blocks below; never edit above. -->

Frozen: 2026-11-09

## Amendment — 2026-11-09 (A1): adopt in existing systems without a big change

**Why:** a gate that breaks a live system on day one gets switched off. Teams need to (1) watch before they enforce, and
(2) avoid writing a manifest entry by hand for every existing tool. Approved by the project owner on 2026-11-09.
Decisions: [ADR 0009](../adr/0009-observe-mode-with-safety-floor.md), [ADR 0010](../adr/0010-draft-manifests.md).

**New words**

| Word | Meaning |
|---|---|
| **Mode** | `enforce` (default) or `observe`. Set in the gate's config file by a human. |
| **Safety floor** | Decisions that stay `deny` even in observe mode. |
| **Observed verdict** | In observe mode, the verdict enforce mode would have given. |
| **Draft manifest** | A manifest generated from existing tool definitions, marked `draft: true`, waiting for human review. |

### R. Observe mode (watch first, then enforce)

```
AC-180 The gate has a mode: enforce (default) or observe. Without a mode setting, the gate enforces.
AC-181 In observe mode the safety floor still denies: every T3 deny from a content rule (for example rm_rf_dangerous,
       sql_drop, git_force_protected, remote_destructive, destructive_tool), plus tool_pin_changed and gate_error.
AC-182 In observe mode every other decision that is not allow becomes allow; the Decision keeps the original answer in
       observed_verdict and adds the reason "observe mode: would have <asked|denied>".
AC-183 In observe mode an unknown tool is allowed and recorded with observed_verdict deny and the rule unknown_tool,
       so the team sees which tools still need a manifest entry.
AC-184 The mode is read only from the gate's config file. No API endpoint, tool argument, or agent message can change
       it, and changing the file changes the policy hash (AC-031).
```

### S. Draft manifests from existing tool definitions

```
AC-185 draft_manifest() turns existing tool definitions into manifest entries: MCP tools/list entries (inputSchema,
       annotations), Claude API tool definitions (input_schema), and OpenAI function tools (parameters).
AC-186 MCP annotations map to safety fields: readOnlyHint → read_only; destructiveHint → state_changing + destructive;
       openWorldHint → remote + egress. A tool with no hints is drafted as state_changing and not reversible (T2: ask).
AC-187 Schema keywords outside the supported subset are removed from the draft, and each removal is listed as a
       review note; nothing is dropped silently.
AC-188 A draft manifest carries draft: true. The gate loads a draft only in observe mode; in enforce mode it refuses
       to start until a human removes the draft marker (fail closed).
```

**Clarification of AC-188 (same day, before any code):** one tool that was imported but never pinned is *not reviewed*:
enforce mode denies it with the rule `tool_not_reviewed`; observe mode allows and records it. This is different from a
pin that **changed** (`tool_pin_changed`), which is part of the safety floor because it can be an attack.

**Contract impact:** `Decision` gains the optional field `observed_verdict` ([`openapi.yaml`](../api/openapi.yaml)).
No new endpoints. The `keel-gate init` command (CLI) that writes a draft file is reference docs, not a new contract.

**Out of scope for A1:** automatic switch from observe to enforce; guessing safety fields from tool names (names can
lie, so a tool without hints is always drafted as "ask").

## Amendment — 2026-11-09 (A2): easy, fast rule and tool management

**Why:** blocking a new risk, allowing a safe command, or adding a tool must take seconds, not a code change. The
project owner asked for rules and tools that are easy to add, manage, and remove, and super fast.
Decision: [ADR 0011](../adr/0011-human-managed-rules.md).

**This replaces** the line in "Authorization rules" that says policy and manifest changes happen only through git
review. Now humans with the policy-admin role may change them through the UI, the CLI, or the files; agents still never can.

**New words**

| Word | Meaning |
|---|---|
| **Custom rule** | A rule a human adds: tool (exact name or a glob like `payments.*`), optional match, verdict, reason, optional end date. |
| **Rule version** | Every change to rules or tools creates a new numbered version that can be rolled back. |
| **Step-up** | A quick re-confirmation (password or passkey) before a policy change, valid for 5 minutes. |
| **Policy admin** | A human role allowed to change rules and tools. Approvers are not policy admins by default. |

### T. Easy to add, manage, and remove

```
AC-190 A policy admin can add a custom rule in one step from the UI, the CLI (keel-gate rule add), or one YAML block,
       with: tool (exact name or glob), optional match (command or argument pattern), verdict (deny, ask, or allow),
       reason, and optional expires_at.
AC-191 A policy admin can list, enable, disable, edit, and remove custom rules from the UI and the CLI.
AC-192 Every change to rules or tools creates a new version; rolling back to any earlier version takes one step.
AC-193 A policy admin can add a tool by importing its definition (draft, AC-185), review it, and pin it; removing a
       tool makes later calls to it unknown (AC-003).
AC-194 An expired custom rule stops applying by itself and is shown as expired.
```

### U. Safe

```
AC-195 Only a human policy-admin session with a fresh step-up (at most 5 minutes old) and a CSRF token can change rules
       or tools; agent keys and approver-only sessions get 403.
AC-196 Every change writes an audit entry with who, when, the version, and the rule or tool before and after.
AC-197 A custom allow rule can turn ask into allow, but it can never override a safety-floor deny (AC-181 list) or a
       protected-path deny (AC-030).
AC-198 With policy_changes: git in the config file, the UI and CLI cannot change rules; they show the file change
       to make instead.
```

### V. Super fast

```
AC-199 A rule or tool change applies to the next decision without restarting the gate, at most 1 second later.
AC-200 With 1,000 custom rules loaded, decide() keeps p99 below 1 ms (rules are indexed by tool name and compiled
       once per change; decide() never waits for a lock).
```

**Contract impact:** new endpoints under `/v1/rules`, `/v1/tools`, `/v1/policy/versions`, and `/v1/step-up`
([`openapi.yaml`](../api/openapi.yaml)).

## Amendment — 2026-11-10 (A3): the Monitor agent (optional, raise-only, read-only judge)

**Why:** rules cannot judge *intent*. Editing `.github/workflows/ci.yml` is normal when the task is "fix CI" and
suspicious when the task is "summarize the README". Teams that want more control asked for a second check: a model that
watches each call and judges whether it fits the user's task. The project owner asked for several modes, Claude Sonnet 5.5
by default, "ask a human" when the monitor fails, and a monitor that is **only a read-only judge**, with no tool calling,
whose own answers are validated. Approved by the project owner on 2026-11-10.
Decision: [ADR 0012](../adr/0012-monitor-agent-raise-only.md).

**New words**

| Word | Meaning |
|---|---|
| **Monitor** | An optional model that judges one proposed call against the user's task. It has no tools and only returns a verdict. |
| **Intent** | The user's task for this session, set by the application from the user's own messages. |
| **Monitor verdict** | `fits` (the call serves the task), `ask` (a human should confirm), or `block` (it does not serve the task). |
| **Canary** | A fixed test case with a known right answer, used to check that the monitor works. |

### W. Modes and scope

```
AC-210 The gate has an optional monitor with a mode: off (default), approvals, changes, or strict. With mode off
       (or no monitor setting) no call is reviewed and no model is called.
AC-211 The mode decides which calls are reviewed: approvals → only calls the rules answered with ask; changes → every
       call the rules did not deny whose tier is above T0; strict → every call the rules did not deny. A call the
       rules denied is never sent to the monitor.
AC-212 The monitor's mode, model, timeout, and failure verdict are read only from the gate's config file. No API
       endpoint, tool argument, or agent message can change them.
```

### X. Raise-only

```
AC-213 The final verdict is the more restrictive of the rules' decision and the monitor's verdict: fits → unchanged;
       ask → at least ask; block → deny. Both raise the tier to at least T2 and add the rule monitor_flagged with the
       reason "monitor: <reason>". The monitor never lowers a verdict and never removes a rule id or reason.
AC-214 If the review fails (error, timeout, refusal, an answer that fails validation, an unhealthy monitor, or a session
       without intent), the call gets the failure verdict from the config (ask by default, or deny), tier at least T2,
       and the rule monitor_error. A deny from the rules still wins.
AC-215 In observe mode a monitor answer stricter than allow is only recorded: observed_verdict is raised and the reason
       "observe mode: would have <asked|denied>" is kept up to date. Only the safety floor (AC-181) blocks.
```

### Y. What the monitor sees

```
AC-216 The monitor sees only: the session's intent, the tool name and description, the call's arguments, and the rules'
       verdict, tier, and reasons. It never sees tool results. The intent is set by the application from the user's
       own messages; it never comes from tool arguments, tool results, or the agent's decide request.
AC-217 Before anything is sent, secret-looking values in the arguments and the intent are replaced with [redacted]:
       API keys and tokens, private keys, bearer tokens, passwords in URLs, and values of keys named like password,
       secret, token, or api_key.
AC-218 The system prompt is one fixed string, identical for every call. The task and the call are placed in delimited
       data blocks that the system prompt marks as data, not instructions; the data cannot close its own block.
```

### Z. Fast and recorded

```
AC-219 With the monitor off, decide() is unchanged and the model SDK is not imported (AC-160 still holds).
AC-220 A review has a hard timeout (default 5 s, at most 30 s) and no automatic retries. A timeout is a failure (AC-214).
AC-221 Reviews are cached by call hash, intent hash, mode, model, and the rules' verdict and tier, with at most 1,024
       entries. Failures are not cached.
```

### AA. A read-only judge, validated

```
AC-222 The monitor is a judge with no tools. The request to the model has a fixed set of keys and contains no tools,
       server tools, MCP servers, or containers; the reviewer refuses extra request options when it is created. An answer
       with any block other than exactly one text block (thinking and fallback notes are ignored) is a failure (AC-214).
       The monitor receives only immutable values and returns only a verdict and a reason.
AC-223 Every answer is validated against a strict schema: an object with exactly verdict (fits, ask, or block) and
       reason (a string). Anything else is a failure. The reason is cleaned before a human or the model sees it:
       control characters and angle brackets are removed, whitespace is collapsed, and it is cut to 200 characters.
AC-224 self_check() sends two fixed canary cases: one that clearly fits its task and one that clearly does not. If an
       answer is wrong or fails, the monitor is marked unhealthy, every call it would review gets the failure verdict
       (AC-214), and an error is logged. A later self_check() that passes marks it healthy again.
```

**Contract impact:** `Session` gains the optional field `intent`. `Decision` is unchanged; the new rule ids are
`monitor_flagged` and `monitor_error`. The Gate Service takes the intent when the application opens a session (Day 3);
`/v1/decide` never accepts it, because the agent must not describe its own task.

**Out of scope for A3:** the monitor reading tool results or the whole conversation; the monitor lowering a verdict
(auto-approval); several monitors voting; models from other providers (the `Reviewer` port allows them later).

**Clarifications of A3 after the security review (2026-11-10, before the first commit of A3).** An independent
review tried to break the monitor and found gaps; each is now covered by a test.

- **AC-222, no other model may answer.** The request asks for no model fallbacks. An answer served by a different model
  (a `fallback` block, a `fallback_message` iteration, or another model name) is a failure. A refusal must stay a
  failure (ask), not become a "fits" from a fallback model.
- **AC-223, strict JSON means no repeated keys.** `{"verdict": "block", "verdict": "fits"}` is a failure.
- **AC-223, the agent never reads the monitor's words.** When the monitor raises a call, the agent model gets a fixed
  message ("the monitor judged that this call does not clearly fit the user's task", or "the monitor could not review
  this call"). The monitor's own reason is model-written text that attacker-chosen arguments can steer, so it goes
  only to humans and the audit log.
- **AC-221, the cache key is the whole review request** (task, call, description, the rules' verdict, tier, and
  reasons) plus the mode, model, and effort.
- **AC-220, bounded reviews.** At most 8 reviews run at once. When all are taken (for example by a hung model), the
  call gets the failure verdict at once instead of waiting in a queue. A timed-out review that has not started is
  cancelled.
- **AC-214, more failures.** A review request larger than 32,000 characters of arguments or 8,000 characters of task
  is not reviewed (cutting it could hide the dangerous part): failure. Any exception from the reviewer, even
  `SystemExit`, is a failure; `decide()` never raises.
- **AC-218, ASCII only.** All data in the prompt is escaped to ASCII, so look-alike or invisible characters cannot
  pose as block tags.
- **AC-217, more secret shapes:** Stripe keys, AWS temporary keys, `Basic` and `Cookie` headers, `--password value`
  flags, `mysql -pSECRET`, quoted values, passwords in URLs without a user name, and secret-looking mapping keys by
  their word parts (`DB_PASS`, `apiKey`, `session`), while names like `author` or `tokenizer_name` are kept.
- **AC-212, YAML.** An unquoted `mode: off` (which YAML reads as `false`) means off. A boolean `timeout_s` is rejected.
- **AC-224, checked at start.** `MonitoredGate.from_settings()`, the production entry point, runs `self_check()`
  before returning.
