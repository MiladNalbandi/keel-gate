"""The monitor eval set (AC-224, layer 3). Offline: checks the cases and the plumbing, never calls a model.

The live run against Claude is scripts/monitor_eval.py; it is billed, so it runs only when a human starts it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from keel_gate.domain.manifest import Manifest
from keel_gate.domain.models import ToolCall, Verdict
from keel_gate.domain.review import MonitorSettings, ReviewRequest, ReviewResult
from keel_gate.gate import Gate, GateSettings
from keel_gate.monitor import MonitoredGate
from tests.factories import TEST_TOOLS, ScriptedReviewer, make_session

CASES: list[dict[str, Any]] = yaml.safe_load((Path(__file__).parent / "cases.yaml").read_text(encoding="utf-8"))[
    "cases"
]


def test_the_eval_set_is_balanced_and_well_formed() -> None:
    ids = [c["id"] for c in CASES]
    kinds = {c["kind"] for c in CASES}

    assert len(CASES) >= 20
    assert len(set(ids)) == len(ids)
    assert kinds == {"on_task", "off_task", "injection"}
    assert {c["expect"] for c in CASES} == {"fits", "not_fits"}
    for case in CASES:
        assert set(case) == {"id", "kind", "intent", "tool", "args", "expect"}, case["id"]
        assert case["tool"] in TEST_TOOLS, case["id"]
        if case["kind"] != "on_task":
            assert case["expect"] == "not_fits", case["id"]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_every_case_reaches_the_monitor_and_its_answer_counts(case: dict[str, Any]) -> None:
    def oracle(request: ReviewRequest) -> ReviewResult:
        return ReviewResult("fits" if case["expect"] == "fits" else "block", "oracle")

    reviewer = ScriptedReviewer(oracle)
    gate = Gate(Manifest.from_mapping(TEST_TOOLS), settings=GateSettings(monitor=MonitorSettings(mode="strict")))
    rules_only = gate.decide(ToolCall(case["tool"], case["args"]), make_session(intent=case["intent"]))

    decision = MonitoredGate(gate, reviewer).decide(
        ToolCall(case["tool"], case["args"]), make_session(intent=case["intent"])
    )

    assert rules_only.verdict is not Verdict.DENY, f"{case['id']}: the rules deny it, so the monitor never sees it"
    assert len(reviewer.requests) == 1
    assert reviewer.requests[0].intent == case["intent"]
    if case["expect"] == "fits":
        assert decision == rules_only
    else:
        assert decision.verdict is Verdict.DENY
        assert "monitor_flagged" in decision.rule_ids
