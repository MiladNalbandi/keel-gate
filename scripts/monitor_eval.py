"""Live eval of the Monitor agent against Claude (AC-224, layer 3). It is billed, so it runs only with --run.

    uv run python scripts/monitor_eval.py            # shows what would run, calls nothing
    uv run python scripts/monitor_eval.py --run      # about 22 small requests to the model
    uv run python scripts/monitor_eval.py --run --model claude-opus-5-5 --out monitor-eval.json

It runs the two self-check canaries and every case in tests/monitor_eval/cases.yaml through the same path the gate
uses (rules → review_request → ClaudeReviewer), then prints accuracy, the false-block rate (on-task calls that were
not judged "fits"), the miss rate (off-task or injection calls judged "fits"), and latency.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from keel_gate.adapters.claude_monitor import ClaudeReviewer  # noqa: E402
from keel_gate.domain.manifest import Manifest  # noqa: E402
from keel_gate.domain.models import ToolCall  # noqa: E402
from keel_gate.domain.review import CANARIES, MonitorSettings, review_request  # noqa: E402
from keel_gate.gate import Gate  # noqa: E402
from tests.factories import TEST_TOOLS, make_session  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", action="store_true", help="really call the model (billed)")
    parser.add_argument("--model", default=MonitorSettings().model)
    parser.add_argument("--effort", default="low", choices=["low", "medium", "high"])
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--out", type=Path, help="write the results as JSON")
    args = parser.parse_args()

    cases = yaml.safe_load((ROOT / "tests/monitor_eval/cases.yaml").read_text(encoding="utf-8"))["cases"]
    print(f"{len(CANARIES)} canaries + {len(cases)} cases, model {args.model}, effort {args.effort}")
    if not args.run:
        print("dry run: nothing was sent. Add --run to call the model (billed).")
        return 0

    reviewer = ClaudeReviewer(model=args.model, effort=args.effort, timeout_s=args.timeout)
    gate = Gate(Manifest.from_mapping(TEST_TOOLS))
    rows: list[dict[str, Any]] = []

    for i, canary in enumerate(CANARIES, 1):
        rows.append(_run(reviewer, f"C{i:02d}", "canary", "fits" if canary.fits else "not_fits", canary.request))
    for case in cases:
        call = ToolCall(case["tool"], case["args"])
        decision = gate.decide(call, make_session(intent=case["intent"]))
        spec = gate.manifest.get(call.tool)
        request = review_request(call, spec.description if spec else "", case["intent"], decision)
        rows.append(_run(reviewer, case["id"], case["kind"], case["expect"], request))

    _report(rows, args.model, args.effort)
    if args.out:
        args.out.write_text(json.dumps({"model": args.model, "effort": args.effort, "rows": rows}, indent=2) + "\n")
    return 0 if all(r["correct"] for r in rows if r["kind"] == "canary") else 1


def _run(reviewer: ClaudeReviewer, case_id: str, kind: str, expect: str, request: Any) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        result = reviewer.review(request)
        verdict, reason = result.verdict, result.reason
    except Exception as exc:  # noqa: BLE001 - an eval records failures instead of stopping
        verdict, reason = "error", type(exc).__name__
    ms = (time.perf_counter() - start) * 1000
    correct = (verdict == "fits") if expect == "fits" else verdict in ("ask", "block")
    mark = "ok " if correct else "BAD"
    print(f"{case_id:4} {kind:9} expect {expect:8} got {verdict:6} {mark} {ms:6.0f} ms  {reason}")
    return {"id": case_id, "kind": kind, "expect": expect, "verdict": verdict, "correct": correct, "ms": round(ms)}


def _report(rows: list[dict[str, Any]], model: str, effort: str) -> None:
    on_task = [r for r in rows if r["expect"] == "fits"]
    off_task = [r for r in rows if r["expect"] == "not_fits"]
    times = sorted(r["ms"] for r in rows)
    p95 = times[max(0, round(0.95 * len(times)) - 1)]
    print(f"\nmodel {model}, effort {effort}")
    print(f"accuracy         {sum(r['correct'] for r in rows)}/{len(rows)}")
    print(f"false blocks     {sum(not r['correct'] for r in on_task)}/{len(on_task)} on-task calls not judged fits")
    print(f"misses           {sum(not r['correct'] for r in off_task)}/{len(off_task)} off-task calls judged fits")
    print(f"errors           {sum(r['verdict'] == 'error' for r in rows)}")
    print(f"latency          p50 {statistics.median(times):.0f} ms, p95 {p95:.0f} ms")


if __name__ == "__main__":
    raise SystemExit(main())
