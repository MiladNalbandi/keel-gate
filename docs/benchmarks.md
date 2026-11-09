# Benchmarks

> **Status: planned.** This page is written on Day 4. The outline below shows what it will cover.

How fast is `decide()`? The target is p99 below 1 ms (AC-160).

## What this page will cover

- Method: 10,000 mixed calls (60% read, 25% shell, 10% refund, 5% egress).
- Results: p50 / p95 / p99 on a laptop and in CI.
- Stretch: AgentAbstain / AgentDojo subsets with and without keel-gate.

Related: [testing](TESTING.md)
