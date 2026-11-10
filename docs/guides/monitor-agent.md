# Turn on the Monitor agent

Rules are fast and exact, but they cannot see **intent**. Editing `.github/workflows/ci.yml` is normal when the user
asked to fix CI. It is suspicious when the user asked for a README summary.

The **Monitor agent** adds a second check for teams that want more control. After the rules decide, a model reads the
user's task and the proposed call and answers: **fits**, **ask**, or **block**.

```text
 tool call ──► 1. rules (< 1 ms) ──► deny? ─────────────────────► ⛔ blocked (the monitor is not called)
                     │ allow / ask
                     ▼
               2. Monitor agent (only if the mode says so)
                  sees: the user's task + this call + the rules' findings
                  answers: fits | ask | block   (strict JSON, no tools)
                     ▼
               3. final answer = the STRICTER of 1 and 2
                  error / timeout / bad answer → ask a human
```

> **Status:** built and tested (Spec 001, Amendment A3; [ADR 0012](../adr/0012-monitor-agent-raise-only.md)).
> Measured accuracy and latency against the live model: see [benchmarks](../benchmarks.md).

## Modes

| Mode | Reviews | Good for |
|---|---|---|
| `off` (default) | nothing. No extra cost or delay. | most teams |
| `approvals` | only calls that would already ask a human. The monitor pre-screens them and flags the bad ones. | busy approvers |
| `changes` | every call that changes something (not T0 read-only) | dev agents with real access |
| `strict` | every call that is not already blocked, reads too (a read can leak data) | high-risk setups |

## Turn it on

```yaml
# keel-gate.yaml (only this file can set the monitor; an agent never can)
monitor:
  mode: changes            # off | approvals | changes | strict
  model: claude-sonnet-5-5 # the default
  timeout_s: 5             # hard limit per review, at most 30
  on_error: ask            # ask (default) | deny
  effort: low              # low | medium | high
```

Write `mode: "off"` with quotes if you can. YAML reads a bare `off` as `false`, which keel-gate also treats as off.

```python
from keel_gate.gate import Gate, load_settings
from keel_gate.monitor import MonitoredGate

gate = Gate(manifest, settings=load_settings(config))
guarded = MonitoredGate.from_settings(gate)  # uses Claude and runs the self-check

session = Session("s1", "support-agent", intent=user_message)  # the task comes from YOUR app, never from the agent
decision = guarded.decide(call, session)  # use it exactly like gate.decide()
```

Claude needs credentials: `ANTHROPIC_API_KEY`, or a profile from `ant auth login`.

## Why it cannot make things worse

| Promise | How |
|---|---|
| **It only raises.** | The final answer is the stricter of the rules and the monitor. A monitor fooled into "fits" changes nothing. The safety floor (`rm -rf ~`, `DROP TABLE`, …) always blocks. |
| **It is a read-only judge.** | The request to the model has a fixed set of fields, with no tools, no web search, no MCP servers, and no code execution. An answer that contains a tool call, or anything other than one JSON object, is rejected. |
| **It fails closed.** | An error, a timeout, a refusal, a bad answer, a failed self-check, a busy monitor, an input too large to review, or a session without a task all lead to "ask a human" (or "deny", if you choose). |
| **Only your model answers.** | No model fallbacks: if the configured model refuses, the call asks a human. An answer from any other model is rejected. |
| **It sees little.** | Only the user's task, the call, and the rules' findings. It never sees tool results, so text injected into web pages or files cannot reach it. Secrets are replaced with `[redacted]` before sending. |
| **The agent never reads its words.** | The reason is cleaned and goes to humans and the audit log only. The agent model gets a fixed message, so tricked arguments cannot make the monitor talk to the agent. |

## Check it before you trust it

- **Every answer** is checked against a strict schema.
- **`self_check()`** sends two canary cases with known answers. `from_settings()` runs it at start. If a canary
  fails, the monitor is marked unhealthy, and every call it would review asks a human.
- **The eval set** (`tests/monitor_eval/cases.yaml`, 20 labeled cases: on-task, off-task, injection) runs offline in CI.
  Live on Claude Sonnet 5.5 it judged none of the off-task calls "fits"
  ([results](../benchmarks.md#the-monitor-agent-live-on-claude-measured-2026-11-10)). The model refuses to judge some
  clearly harmful calls; a refusal asks a human, and refusing the off-task canary passes the self-check.
  To measure the real model, run it live (it is billed, so it never runs by itself):

```bash
uv run --extra anthropic python scripts/monitor_eval.py --run
```

Two other ways to run the same eval:

- **No API key, but a Claude subscription:** `--via claude-code` sends the same prompt through `claude -p`, with safe
  mode on and every tool turned off. The numbers include the CLI start-up time, so the model time is printed too.
- **In GitHub Actions:** add an `ANTHROPIC_API_KEY` repository secret, then start the **Monitor eval** workflow by
  hand. It uploads `monitor-eval.json` as an artifact. It never runs on pushes, pull requests, or forks.

## Costs and limits

- Each reviewed call waits for a model: p50 2.0 s, p95 2.8 s in the live eval. Repeated calls are cached.
- It costs a little money per reviewed call. Use `approvals` or `changes` to review fewer calls.
- Call data goes to the model provider's API. Do not turn it on for data that must not leave your network.
- Its judgement is probabilistic. It is a **second** layer, never the only one.
