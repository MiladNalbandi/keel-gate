# keel-gate

**A safety brake between AI agents and their tools. It stops actions you can't undo.**

```text
 AI agent ──► "ls -la"              ──► keel-gate ──►  ✅ run          (safe)
              "refund $500"                       ──►  📱 ask a human  (hard to undo)
              "rm -rf ~"                          ──►  ⛔ block        (catastrophic)
```

> **Part of [Keel](https://github.com/MiladNalbandi/keel-v2).** keel-gate is Keel's action gate, moved into its own
> repo for the Drawerrr AI Safety Challenge *Prevent irreversible autonomous actions*.
>
> **Status (Nov 10, 2026): working prototype.** Built and tested: the decision engine and the optional Monitor agent.
> Next: approvals, mandates, protected paths, taint, egress, the demo, and the adapters. 🔜 marks planned parts.

## What it stops

| The agent tries… | keel-gate today |
|---|---|
| `rm -rf ~`, `DROP TABLE users`, `git push --force origin main` | ⛔ blocks: these cannot be undone |
| the same, hidden: `bash -c '…'`, base64 piped to `sh`, `"r""m" -rf ~` | ⛔ / 📱 parses the shell for real |
| a $500 refund, `curl` to an unknown host | 📱 asks a human (one-time approval tokens 🔜) |
| editing CI when you asked for a README summary | ⛔ / 📱 the optional Monitor agent flags it |
| editing its own settings (`.claude/`, `.mcp.json`) | 🔜 protected paths (Day 2) |
| reading `.env`, then sending it out | 📱 asks today; ⛔ with taint + egress 🔜 |

When something is blocked, the model gets a clear tool error, so it can stop or ask you.

## Try it in 1 minute

```bash
git clone https://github.com/MiladNalbandi/keel-gate && cd keel-gate
uv sync
uv run pytest -q               # 655 tests
uv run pytest -q -m redteam    # attacks taken from real incidents
```

## Use it in your code

```python
from keel_gate.domain.manifest import Manifest
from keel_gate.domain.models import Session, ToolCall
from keel_gate.gate import Gate

schema = {"type": "object", "required": ["command"], "properties": {"command": {"type": "string"}}}
shell = {"kind": "shell", "description": "Run a shell command.", "schema": schema}
shell |= {"read_only": False, "state_changing": True, "reversible": False}
gate = Gate(Manifest.from_mapping({"shell": shell}))
decision = gate.decide(ToolCall("shell", {"command": "rm -rf ~"}), Session("s1", "dev-agent", workspace="/work"))
print(decision.verdict, decision.message_for_model)  # deny  keel-gate blocked this call: recursive delete of '~' …
```

Already running agents? Start in observe mode: [add to an existing system](docs/guides/integrate-existing-systems.md).

## Want more control? Turn on the Monitor agent

An optional model reads the user's task and each call, and answers *fits*, *ask*, or *block*. It is a **read-only
judge**: it has no tools, it can only make answers **stricter**, and if it fails the call asks a human. Choose how much
it reviews: `off` · `approvals` · `changes` · `strict`. Read [the Monitor agent guide](docs/guides/monitor-agent.md).

## Overview

Agents act fast and notice risk late. In the challenge's own study, agents kept acting in 40.5% of cases where harm was
possible, and real agents have deleted production databases. keel-gate checks **every tool call before it runs**,
outside the model.

## Safety approach

One fail-closed check per call: **parse** the call (a real shell parser, not string matching), **classify** its risk
tier, apply the human-managed **rules**, and **decide** allow / ask / deny. The strictest answer wins, and no rule
can weaken the safety floor. Optionally, the **Monitor agent** judges intent and can only raise the answer.
Details: [how it works](docs/how-it-works.md).

## Evidence

- 655 tests, 95% coverage, type-checked (`mypy --strict`).
- 9 of 22 attack tests named after real incidents run and pass today (Replit, Antigravity, Cursor, Ona, goal hijack,
  injection against the monitor). See [red-team results](docs/red-team.md).
- Monitor agent, live on Claude Sonnet 5.5: off-task or injected calls that got through fell from 7 of 11 (rules
  alone) to 0 of 11, with no extra friction on on-task calls; about 2 s per review.
- `decide()` p99 is 0.04 ms, 25 times under the 1 ms target. See [benchmarks](docs/benchmarks.md).

## Limitations

It cannot judge intent inside an allowed action unless the Monitor agent is on, and the monitor is probabilistic. It is
not an OS sandbox, so use both. Several layers are still planned. Read [limitations](docs/limitations.md).

## Learn more

[Docs](docs/index.md) · [Spec](docs/specs/SPEC-001-keel-gate.md) · [Architecture](docs/architecture.md) ·
[Threat model](docs/threat-model.md) · [Research](docs/research.md) · [Glossary](docs/glossary.md)

MIT licensed. Parts adapted from [keel v2](https://github.com/MiladNalbandi/keel-v2).
