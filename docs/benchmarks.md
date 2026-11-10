# Benchmarks

How fast is `decide()`? The target is **p99 below 1 ms** (AC-160), also with 1,000 custom rules (AC-200).

## Method

- 99 mixed calls, repeated 100 times (9,900 decisions) after one warm-up round:
  - 60 file reads
  - 24 shell commands (safe ones, plus `rm -rf ~`, a force push, `DROP TABLE`, and base64 piped to `sh`)
  - 10 refunds
  - 5 web fetches
- The timer covers the whole `decide()` call, from the tool call in to the Decision out.
- Script: the same calls as `tests/perf/test_speed.py`, which also runs in CI with a looser limit.

## Results (measured 2026-11-10)

| Setup | p50 | p95 | p99 |
|---|---|---|---|
| Rules only, no custom rules | 0.008 ms | 0.011 ms | 0.015 ms |
| Rules only, 1,000 custom rules | 0.008 ms | 0.020 ms | 0.040 ms |
| `MonitoredGate`, monitor `off` | 0.008 ms | 0.011 ms | 0.015 ms |
| `MonitoredGate`, `strict`, answer already cached | 0.034 ms | 0.046 ms | 0.050 ms |

Machine: Apple Silicon laptop (arm64), Python 3.12.7. On the Linux test server (Python 3.12), three runs measured
p99 0.052–0.078 ms with no custom rules and 0.102–0.127 ms with 1,000 rules.

**In short:** every setup is at least 20 times under the 1 ms target on the laptop, and at least 7 times under it on
the server. The Monitor agent adds nothing when it is
off. A cached review costs about 0.03 ms more, mostly secret redaction of the call.

## The Monitor agent's own cost

A review that is not cached waits for the model. That time is network plus model latency, not gate time. Measure it
with the live eval, which is billed, so it never runs by itself:

```bash
uv run --extra anthropic python scripts/monitor_eval.py --run
```

It prints accuracy, the false-block rate, the miss rate, and p50/p95 latency for 2 canaries plus 20 labeled cases.

> **Not measured yet:** the live run against Claude Sonnet 5.5 needs the owner's OK, because it costs money.

## Planned

- AgentAbstain / AgentDojo subsets with and without keel-gate (stretch, Day 4).

Related: [testing](TESTING.md)
