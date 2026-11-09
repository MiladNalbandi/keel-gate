"""AC-160 and AC-200: decide() stays fast, also with 1,000 custom rules.

CI machines are slower and noisier than laptops, so CI uses a looser limit (set CI=1).
"""

from __future__ import annotations

import os
import time

import pytest

from keel_gate.domain.manifest import Manifest
from keel_gate.domain.models import ToolCall
from keel_gate.domain.rules import CustomRule
from keel_gate.gate import Gate
from tests.factories import TEST_TOOLS, make_session

LIMIT_MS = 5.0 if os.environ.get("CI") else 1.0

COMMANDS = [
    "ls -la",
    "git status",
    "rm -rf ~",
    "git push --force origin main",
    "psql -c 'DROP TABLE x'",
    "echo cm0gLXJmIH4= | base64 -d | sh",
    "bash -c 'rm -rf ~'",
    "npm test",
    "git commit -m x",
    "find . -name '*.py'",
    "terraform destroy -auto-approve",
    "cat README.md | grep x",
]


def _mixed_calls() -> list[ToolCall]:
    calls = [ToolCall("read_file", {"path": f"src/f{i}.py"}) for i in range(60)]
    calls += [ToolCall("shell", {"command": c}) for c in COMMANDS * 2]
    calls += [ToolCall("payments.refund", {"order": str(i), "amount": "10.00"}) for i in range(10)]
    calls += [ToolCall("web.fetch", {"url": f"https://example.com/{i}"}) for i in range(5)]
    return calls


def _thousand_rules() -> list[CustomRule]:
    rules = [
        CustomRule.create(id=f"ru_tool{i:05d}", tool=f"crm.tool_{i}", verdict="deny", reason="sample")
        for i in range(800)
    ]
    rules += [
        CustomRule.create(id=f"ru_glob{i:05d}", tool=f"svc{i}.*", verdict="ask", reason="sample") for i in range(150)
    ]
    rules += [
        CustomRule.create(id=f"ru_shell{i:04d}", tool="shell", match=f"tool{i} *", verdict="deny", reason="sample")
        for i in range(50)
    ]
    return rules


def _p99_ms(gate: Gate, rounds: int = 100) -> float:
    session = make_session()
    calls = _mixed_calls()
    for call in calls:  # warm up caches once, like a running gate
        gate.decide(ToolCall(call.tool, dict(call.args)), session)
    times: list[float] = []
    for _ in range(rounds):
        for call in calls:
            fresh = ToolCall(call.tool, dict(call.args))
            start = time.perf_counter()
            gate.decide(fresh, session)
            times.append(time.perf_counter() - start)
    times.sort()
    return times[int(len(times) * 0.99)] * 1000


@pytest.mark.slow
def test_ac_160_decide_p99_is_below_the_limit() -> None:
    gate = Gate(Manifest.from_mapping(TEST_TOOLS))

    assert _p99_ms(gate) < LIMIT_MS


@pytest.mark.slow
def test_ac_200_decide_stays_fast_with_1000_custom_rules() -> None:
    rules = _thousand_rules()
    gate = Gate(Manifest.from_mapping(TEST_TOOLS), rules=rules)

    assert len(rules) == 1000
    assert _p99_ms(gate) < LIMIT_MS
