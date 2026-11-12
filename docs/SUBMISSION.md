# Drawerrr submission: keel-gate

> **Status: working prototype (Nov 11, 2026).** Built and tested: the decision engine, protected paths, and the
> optional Monitor agent. Next: approvals, mandates, taint, egress, the audit log, the demo, and the adapters.
> 🔜 marks planned parts. This page is updated with each submission.
>
> **Origin:** keel-gate is part of [Keel](https://github.com/MiladNalbandi/keel-v2), moved into its own repo for this challenge.

**Challenge:** Prevent irreversible AI autonomous actions (Drawerrr AI Safety Challenge, deadline Nov 15, 2026).
**Award categories it targets:** digital system changes · delegated actions · financial transactions · consequential
decisions · information access · physical-world actions.

## Project overview

keel-gate is a fail-closed **action firewall** between AI agents and their tools. Every tool call is checked before it runs,
outside the model, and gets one of three answers: run it, ask a human for this exact action, or block it.
It is built to work with the Claude API, Claude Code, the Agent SDK, OpenAI, and MCP, or as a web service. Today it is a
Python library; the adapters are next.

## Safety approach

- Deterministic decisions outside the model, in the shape of the OWASP Agent Control Standard.
- Real shell parsing (a syntax tree, not string matching), risk tiers T0–T3, and a safety floor that no custom rule
  and no mode can weaken.
- Protected paths: the agent cannot edit its own settings (`.claude/`, `.mcp.json`, …), git hooks, or the gate's policy.
- Tool pinning: a tool whose definition changes is blocked until a human reviews and re-pins it.
- Observe mode for existing systems: watch first, enforce later; the safety floor still blocks.
- Optional **Monitor agent**: a model that judges each call against the user's task. It is a read-only judge with no
  tools, it can only make answers stricter, a failure asks a human, and it has modes (off, approvals, changes, strict).
- 🔜 One-time approvals bound to the exact call (sha256), out-of-band, expiring; mandates for routine limited actions.
- 🔜 Taint tracking after untrusted input or secrets (inspired by Google DeepMind's CaMeL), and egress rules.
- 🔜 A hash-chained audit log and an Agent History report.

Read more: [how it works](how-it-works.md) · [architecture](architecture.md) · [threat model](threat-model.md).

## Supporting evidence

- 787 tests, 94% coverage, `mypy --strict`, and CI on every push.
- Red team: 16 of 29 attack cases (104 steps) run and pass today: [results](red-team.md).
  - 9 are built from real incidents and known attacks (Replit, Antigravity, Cursor, Ona, weakened rules, goal
    hijack, and attacks on the Monitor agent).
  - 7 come from our own red team. It proved 44 bypasses in an offline sandbox: 26 risky calls allowed with no human
    and 18 catastrophic calls that only asked. All 44 are fixed and stay as tests.
- Monitor agent live on Claude Sonnet 5.5 (2026-11-10): off-task or injected calls allowed with no human fell from 7
  of 11 (rules alone) to 0 of 11; on-task calls held stayed at 2 of 9; p50 2.0 s per review.
- Property-based tests: any change to the arguments changes the call fingerprint that approvals will be bound to, and
  generated obfuscations of `rm -rf` are never allowed.
- Speed: `decide()` p99 0.029 ms, and 0.055 ms with 1,000 custom rules: [benchmarks](benchmarks.md).
- Demo video (2 minutes): [keel-gate-demo.mp4](demo/keel-gate-demo.mp4). Every decision in it is live
  `Gate.decide()` output, and nothing is executed; only the Monitor agent's answer is scripted, as the video says.
  Re-make it with `uv run --with pillow python scripts/demo_video.py`.
- Report: 🔜 (Day 5).

## Limitations

See [limitations](limitations.md). In short: it cannot judge intent inside an allowed action unless the Monitor agent
is on, and the monitor is probabilistic. It is not an OS sandbox, so use both. Several layers are still planned.

## Reproduce it

See [getting started](getting-started.md). Everything runs in a mocked world: no real money, email, or servers.
