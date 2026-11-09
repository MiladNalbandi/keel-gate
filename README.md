# keel-gate

**A safety brake between AI agents and their tools. It stops actions you can't undo.**

```text
 AI agent ──► "DROP TABLE customers"  ──► keel-gate ──►  ✅ run          (safe)
              "refund $500"                          ──►  📱 ask a human  (hard to undo)
              "rm -rf ~"                             ──►  ⛔ block        (catastrophic)
```

> Status: **design phase**. The spec, contract, and decisions are ready for review; the code comes next.
> Built for the Drawerrr AI Safety Challenge *Prevent irreversible autonomous actions*.

## What it stops

| The agent tries… | keel-gate does | Why |
|---|---|---|
| `rm -rf ~` or `DROP TABLE users` | ⛔ blocks | cannot be undone |
| a $500 refund | 📱 asks a human, for this exact refund only | money leaves the company |
| a $20 refund inside today's limit | ✅ runs | a human set the limit before (a *mandate*) |
| reading `.env`, then `curl evil.com` | ⛔ blocks | secrets must not leave |
| editing its own settings (`.claude/`, `.mcp.json`) | ⛔ blocks | an agent must not change its own rules |

When something is blocked, the model gets a clear tool error, so it can stop or ask you.

## Try it in 1 minute

```bash
uv sync --all-extras
uv run keel-gate demo          # runs a developer agent and a support agent in a fake world
open demo/out/report.html      # see every decision: allowed, asked, blocked
```

## Use it with your agent

**Claude API (Python)**: put the gate where your app runs tools:

```python
gate = Gate.from_dir("policies/")
result = gate.run_tool_use(block, session)  # returns the tool_result to send back to Claude
```

**Claude Code**: add a `PreToolUse` hook in `.claude/settings.json` that runs `keel-gate hook`.

**MCP (claude.ai and other clients)**: run `keel-gate mcp-proxy` in front of your MCP servers.

**Already running agents?** Start in observe mode and draft the manifest from your tools:
[add to an existing system](docs/guides/integrate-existing-systems.md) · [manage rules](docs/guides/manage-rules-and-tools.md).

More: [run it on Claude](docs/guides/protect-claude-code.md) · [OpenAI](docs/guides/protect-openai-app.md) ·
[your own server](docs/guides/run-gate-service.md).

## Overview

Agents act fast and notice risk late. Even the best models stop correctly only about 60% of the time, and real agents have
deleted production databases. keel-gate checks **every tool call before it runs**, outside the model.

## Safety approach

One fail-closed check per call:

1. **Parse** the call (real shell parsing, not string matching).
2. **Classify** its risk tier.
3. **Check** taint, egress, identity, and protected paths.
4. **Decide** allow / ask / deny; the strictest answer wins.

Approvals are one-time and bound to the exact arguments. Every decision goes into a tamper-evident log.
Details: [how it works](docs/how-it-works.md).

## Evidence

16 attack tests, each named after a real incident (Replit, PocketOS, GitHub MCP, Air Canada …), plus speed tests
(target p99 < 1 ms). See [red-team results](docs/red-team.md) and [benchmarks](docs/benchmarks.md).

## Limitations

It cannot judge intent *inside* an allowed action, and it is not an OS sandbox. Use both. Read
[limitations](docs/limitations.md).

## Learn more

[Docs](docs/index.md) · [Spec](docs/specs/SPEC-001-keel-gate.md) · [Architecture](docs/architecture.md) ·
[Threat model](docs/threat-model.md) · [Research](docs/research.md) · [Glossary](docs/glossary.md)

MIT licensed. Parts adapted from [keel v2](https://github.com/MiladNalbandi/keel-v2).
