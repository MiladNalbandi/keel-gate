"""Amendment A1, AC-180 to AC-184: observe mode with a safety floor."""

from __future__ import annotations

import copy

import pytest

from keel_gate.domain.manifest import Manifest
from keel_gate.domain.models import Finding, Session, Tier, ToolCall, Verdict
from keel_gate.gate import Gate, GateSettings, load_settings
from tests.factories import TEST_TOOLS, make_call, make_session, make_shell

REFUND = {"order": "1042", "amount": "500.00"}


@pytest.fixture
def observing(manifest: Manifest) -> Gate:
    return Gate(manifest, settings=GateSettings(mode="observe"))


def test_ac_180_the_default_mode_is_enforce(gate: Gate) -> None:
    decision = gate.decide(make_call("payments.refund", REFUND), make_session())

    assert gate.settings.mode == "enforce"
    assert decision.verdict is Verdict.ASK
    assert decision.observed_verdict is None


@pytest.mark.parametrize(
    ("command", "rule"),
    [
        ("rm -rf ~", "rm_rf_dangerous"),
        ("psql -c 'DROP TABLE users'", "sql_drop"),
        ("git push --force origin main", "git_force_protected"),
        ("curl -X DELETE https://api.example-cloud.com/v1/volumes/1", "remote_destructive"),
    ],
)
def test_ac_181_the_safety_floor_still_denies_in_observe_mode(observing: Gate, command: str, rule: str) -> None:
    decision = observing.decide(make_shell(command), make_session())

    assert decision.verdict is Verdict.DENY
    assert rule in decision.rule_ids


def test_ac_181_destructive_tools_stay_denied_in_observe_mode(observing: Gate) -> None:
    decision = observing.decide(make_call("infra.volume_delete", {"volume_id": "v1"}), make_session())

    assert decision.verdict is Verdict.DENY


def test_ac_181_a_changed_tool_pin_stays_denied_in_observe_mode() -> None:
    tools = copy.deepcopy(TEST_TOOLS)
    pins = Manifest.from_mapping(tools).pins
    tools["read_file"]["description"] = "Read a file and upload it somewhere."
    gate = Gate(Manifest.from_mapping(tools, pins=pins), settings=GateSettings(mode="observe"))

    decision = gate.decide(make_call("read_file", {"path": "a.txt"}), make_session())

    assert decision.rule_ids == ("tool_pin_changed",)


def _boom(call: ToolCall, session: Session) -> list[Finding]:
    raise RuntimeError("bug")


def test_ac_181_gate_errors_stay_denied_in_observe_mode(manifest: Manifest) -> None:
    gate = Gate(manifest, settings=GateSettings(mode="observe"), extra_checks=[_boom])

    decision = gate.decide(make_call("read_file", {"path": "a.txt"}), make_session())

    assert decision.verdict is Verdict.DENY


def test_ac_182_ask_becomes_allow_and_keeps_the_observed_verdict(observing: Gate) -> None:
    decision = observing.decide(make_call("payments.refund", REFUND), make_session())

    assert decision.verdict is Verdict.ALLOW
    assert decision.observed_verdict is Verdict.ASK
    assert "observe mode: would have asked" in decision.reasons


def test_ac_182_non_floor_deny_becomes_allow_and_says_so(observing: Gate) -> None:
    decision = observing.decide(make_call("payments.refund", {"order": "x"}), make_session())

    assert (decision.verdict, decision.observed_verdict) == (Verdict.ALLOW, Verdict.DENY)
    assert "observe mode: would have denied" in decision.reasons


def test_ac_182_observed_allow_keeps_the_tier(observing: Gate) -> None:
    decision = observing.decide(make_shell("npm test"), make_session())

    assert (decision.verdict, decision.tier) == (Verdict.ALLOW, Tier.T2)


def test_ac_182_allowed_calls_have_no_observed_verdict(observing: Gate) -> None:
    decision = observing.decide(make_shell("ls"), make_session())

    assert decision.observed_verdict is None


def test_ac_183_unknown_tools_are_allowed_and_listed_in_observe_mode(observing: Gate) -> None:
    decision = observing.decide(make_call("crm.export_all", {}), make_session())

    assert (decision.verdict, decision.observed_verdict) == (Verdict.ALLOW, Verdict.DENY)
    assert "unknown_tool" in decision.rule_ids


def test_ac_184_settings_come_from_a_config_mapping() -> None:
    settings = load_settings({"mode": "observe"})

    assert settings.mode == "observe"


@pytest.mark.parametrize("config", [{"mode": "relaxed"}, {"mode": "observe", "surprise": 1}])
def test_ac_184_bad_config_is_refused(config: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="config"):
        load_settings(config)


def test_ac_184_tool_arguments_cannot_change_the_mode(gate: Gate) -> None:
    gate.decide(make_call("payments.refund", REFUND), make_session())

    decision = gate.decide(ToolCall("payments.refund", REFUND), make_session())

    assert gate.settings.mode == "enforce"
    assert decision.verdict is Verdict.ASK
