"""Red-team scenarios from real incidents. Each YAML file in cases/ is one incident.

A step passes when the verdict matches `expect.verdict`, or is one of `expect.verdict_in`; when given, the tier and
rule must match too.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from keel_gate.domain.manifest import Manifest
from keel_gate.domain.models import ToolCall
from keel_gate.domain.rules import rules_from_mapping
from keel_gate.gate import Gate
from tests.factories import TEST_TOOLS, make_session

CASES = sorted((Path(__file__).parent / "cases").glob("*.yaml"))


def _load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


def _steps() -> list[Any]:
    out = []
    for path in CASES:
        case = _load(path)
        for i, step in enumerate(case["steps"]):
            out.append(pytest.param(case, step, id=f"{case['id']}-{i + 1}"))
    return out


@pytest.mark.redteam
@pytest.mark.parametrize(("case", "step"), _steps())
def test_redteam_step(case: dict[str, Any], step: dict[str, Any]) -> None:
    rules = rules_from_mapping({"rules": case.get("custom_rules", [])})
    gate = Gate(Manifest.from_mapping(TEST_TOOLS), rules=rules)
    session = make_session(**case.get("session", {}))

    decision = gate.decide(ToolCall(tool=step["tool"], args=step["args"]), session)

    expect = step["expect"]
    allowed = expect.get("verdict_in", [expect.get("verdict")])
    assert decision.verdict.value in allowed, f"{case['incident']}: got {decision.verdict} {decision.rule_ids}"
    if "tier" in expect:
        assert decision.tier.value == expect["tier"]
    if "rule" in expect:
        assert expect["rule"] in decision.rule_ids
