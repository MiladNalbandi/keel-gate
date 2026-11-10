"""Red-team scenarios from real incidents. Each YAML file in cases/ is one incident.

A step passes when the verdict matches `expect.verdict`, or is one of `expect.verdict_in`; when given, the tier and
rule must match too.

Cases with a `monitor:` block run through the Monitor agent (Amendment A3). The model is replaced by a fake client
that returns the step's `monitor_response`: `{verdict, reason}` for a normal answer, `{blocks: [...]}` for raw content
blocks, and `delay_s` for a slow answer. `expect.monitor_called` checks whether the monitor was asked at all.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from keel_gate.adapters.claude_monitor import ClaudeReviewer
from keel_gate.domain.manifest import Manifest
from keel_gate.domain.models import Decision, ToolCall
from keel_gate.domain.review import MonitorSettings
from keel_gate.domain.rules import rules_from_mapping
from keel_gate.gate import Gate, GateSettings
from keel_gate.monitor import MonitoredGate
from tests.factories import TEST_TOOLS, FakeAnthropic, make_session, model_response

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


def _fake_model(answer: dict[str, Any]) -> FakeAnthropic:
    if "blocks" in answer:
        blocks = [SimpleNamespace(**block) for block in answer["blocks"]]
        response = model_response(*blocks, stop_reason=answer.get("stop_reason", "end_turn"))
    else:
        text = json.dumps({"verdict": answer["verdict"], "reason": answer["reason"]})
        response = model_response(SimpleNamespace(type="text", text=text))
    return FakeAnthropic(response, delay_s=answer.get("delay_s", 0.0))


def _decide(case: dict[str, Any], step: dict[str, Any]) -> tuple[Decision, FakeAnthropic | None]:
    rules = rules_from_mapping({"rules": case.get("custom_rules", [])})
    monitor = case.get("monitor")
    settings = GateSettings(monitor=MonitorSettings.from_mapping(monitor)) if monitor else GateSettings()
    gate = Gate(Manifest.from_mapping(TEST_TOOLS), settings=settings, rules=rules)
    session = make_session(**case.get("session", {}))
    call = ToolCall(tool=step["tool"], args=step["args"])
    if not monitor:
        return gate.decide(call, session), None
    client = _fake_model(step.get("monitor_response", {"verdict": "fits", "reason": "ok"}))
    guarded = MonitoredGate(gate, ClaudeReviewer.from_settings(settings.monitor, client=client))
    try:
        return guarded.decide(call, session), client
    finally:
        guarded.close()


@pytest.mark.redteam
@pytest.mark.parametrize(("case", "step"), _steps())
def test_redteam_step(case: dict[str, Any], step: dict[str, Any]) -> None:
    decision, client = _decide(case, step)

    expect = step["expect"]
    allowed = expect.get("verdict_in", [expect.get("verdict")])
    assert decision.verdict.value in allowed, f"{case['incident']}: got {decision.verdict} {decision.rule_ids}"
    if "tier" in expect:
        assert decision.tier.value == expect["tier"]
    if "rule" in expect:
        assert expect["rule"] in decision.rule_ids
    if "monitor_called" in expect:
        assert client is not None, "monitor_called needs a monitor block in the case"
        assert bool(client.requests) is expect["monitor_called"]
        for sent in client.requests:
            assert "tools" not in sent, "the monitor must never get tools (AC-222)"
