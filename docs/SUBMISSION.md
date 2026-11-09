# Drawerrr submission: keel-gate

> **Status: draft.** The evidence sections are filled in from real test results on Days 4–5.

**Challenge:** Prevent irreversible AI autonomous actions (Drawerrr AI Safety Challenge, deadline Nov 15, 2026).
**Award categories covered:** digital system changes · delegated actions · financial transactions · consequential decisions ·
information access · physical-world actions.

## Project overview

keel-gate is a fail-closed **action firewall** between AI agents and their tools. Every tool call is checked before it runs,
outside the model, and gets one of three answers: run it, ask a human for this exact action, or block it.
It works with the Claude API, Claude Code, the Agent SDK, OpenAI, and MCP, or as a web service.

## Safety approach

- Deterministic decisions outside the model, in the shape of the OWASP Agent Control Standard.
- Real shell parsing, risk tiers T0–T3, protected paths, egress rules, and identity from the session.
- Taint tracking after untrusted input or secrets (inspired by Google DeepMind's CaMeL).
- One-time approvals bound to the exact call (sha256), out-of-band, expiring; mandates for routine limited actions.
- A hash-chained audit log and an Agent History report.

Read more: [how it works](how-it-works.md) · [architecture](architecture.md) · [threat model](threat-model.md).

## Supporting evidence

- 16 red-team tests built from real incidents: [results](red-team.md).
- Property-based tests (approvals cannot cover changed arguments; budgets cannot be overspent).
- Speed: [benchmarks](benchmarks.md).
- Demo video and report: *(Day 5)*.

## Limitations

See [limitations](limitations.md). In short: it cannot judge intent inside an allowed action, it is not an OS sandbox, and
taint is tracked per session, not per value.

## Reproduce it

See [getting started](getting-started.md). Everything runs in a mocked world: no real money, email, or servers.
