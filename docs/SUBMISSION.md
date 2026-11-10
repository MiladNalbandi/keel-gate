# Drawerrr submission: keel-gate

> **Status: working prototype (Nov 10, 2026).** The decision engine and the optional Monitor agent are built and tested.
> Approvals, mandates, protected paths, taint, egress, the demo, and the adapters are next. This page is updated with
> each submission.
>
> **Origin:** keel-gate is part of [Keel](https://github.com/MiladNalbandi/keel-v2), moved into its own repo for this challenge.

**Challenge:** Prevent irreversible AI autonomous actions (Drawerrr AI Safety Challenge, deadline Nov 15, 2026).
**Award categories covered:** digital system changes · delegated actions · financial transactions · consequential decisions ·
information access · physical-world actions.

## Project overview

keel-gate is a fail-closed **action firewall** between AI agents and their tools. Every tool call is checked before it runs,
outside the model, and gets one of three answers: run it, ask a human for this exact action, or block it.
It is built to work with the Claude API, Claude Code, the Agent SDK, OpenAI, and MCP, or as a web service. Today it is a
Python library; the adapters are next.

## Safety approach

- Deterministic decisions outside the model, in the shape of the OWASP Agent Control Standard.
- Real shell parsing, risk tiers T0–T3, protected paths, egress rules, and identity from the session.
- Taint tracking after untrusted input or secrets (inspired by Google DeepMind's CaMeL).
- One-time approvals bound to the exact call (sha256), out-of-band, expiring; mandates for routine limited actions.
- A hash-chained audit log and an Agent History report (planned).
- Optional **Monitor agent**: a model that judges each call against the user's task. It is a read-only judge with no
  tools, it can only make answers stricter, a failure asks a human, and it has modes (off, approvals, changes, strict).

Read more: [how it works](how-it-works.md) · [architecture](architecture.md) · [threat model](threat-model.md).

## Supporting evidence

- 655 tests, 95% coverage, `mypy --strict`.
- Monitor agent live on Claude Sonnet 5.5 (2026-11-10): off-task or injected calls allowed with no human fell from 7
  of 11 (rules alone) to 0 of 11; on-task calls held stayed at 2 of 9; p50 2.0 s per review.
- 22 red-team tests built from real incidents and attacks; 9 run and pass today: [results](red-team.md).
- Property-based tests: any change to the arguments changes the call fingerprint that approvals are bound to, and
  generated obfuscations of `rm -rf` are never allowed.
- Speed: `decide()` p99 0.04 ms: [benchmarks](benchmarks.md).
- Demo video and report: *(Day 5)*.

## Limitations

See [limitations](limitations.md). In short: it cannot judge intent inside an allowed action, it is not an OS sandbox, and
taint is tracked per session, not per value.

## Reproduce it

See [getting started](getting-started.md). Everything runs in a mocked world: no real money, email, or servers.
