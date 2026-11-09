# Getting started

> **Status: planned.** The commands below are the target for Day 5. Until then, this page is the plan.

About 10 minutes. You need [uv](https://docs.astral.sh/uv/) and Python 3.12.

## 1. Install

```bash
git clone <this repo>
cd keel-gate
uv sync --all-extras
```

## 2. Run the demo

```bash
uv run keel-gate demo
```

Two scripted agents work in a fake world (no real money, email, or servers):

- a **developer agent**: it reads code, commits, then tries `DROP TABLE` and `rm -rf`
- a **customer-support agent**: small refunds inside a mandate, a $500 refund, a data export to an unknown host

You see each decision in the terminal: ✅ allow, 📱 ask, ⛔ deny.

## 3. Approve from your phone

```bash
uv run keel-gate serve      # opens the inbox at http://localhost:8787
```

Open the inbox, find the $500 refund card, check the binding code, and tap **Approve once**. Then try to replay the same
approval with a different amount: it is rejected.

## 4. Read the report

```bash
open demo/out/report.html
uv run keel-gate audit verify demo/out/audit.jsonl
```

Change one line in `audit.jsonl` and run `verify` again: it finds the change.

## Next

- Protect your own agent: [Claude Code](guides/protect-claude-code.md) · [Claude API](guides/protect-claude-api-app.md) ·
  [OpenAI](guides/protect-openai-app.md) · [MCP](guides/protect-mcp-tools.md)
- Write your rules: [write a policy](guides/write-a-policy.md)
