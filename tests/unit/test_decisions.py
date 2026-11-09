"""AC-001, AC-002: the Decision shape and "the most restrictive verdict wins"."""

from __future__ import annotations

import re

import pytest

from keel_gate.domain.combine import combine
from keel_gate.domain.models import Decision, Finding, Tier, Verdict
from keel_gate.gate import Gate
from tests.factories import make_call, make_session

HASH = "a" * 64


def _f(verdict: Verdict, tier: Tier, rule: str) -> Finding:
    return Finding(verdict=verdict, tier=tier, rule_id=rule, reason=f"because {rule}")


def test_ac_001_decide_returns_a_full_decision(gate: Gate) -> None:
    # Act
    decision = gate.decide(make_call("read_file", {"path": "README.md"}), make_session())

    # Assert
    assert isinstance(decision, Decision)
    assert decision.verdict in set(Verdict)
    assert decision.tier in set(Tier)
    assert isinstance(decision.reasons, tuple)
    assert decision.reasons
    assert isinstance(decision.rule_ids, tuple)
    assert decision.rule_ids
    assert re.fullmatch(r"[0-9a-f]{64}", decision.call_hash)


def test_ac_001_decision_hash_is_the_call_hash(gate: Gate) -> None:
    call = make_call("read_file", {"path": "README.md"})

    decision = gate.decide(call, make_session())

    assert decision.call_hash == call.call_hash


@pytest.mark.parametrize(
    ("verdicts", "expected"),
    [
        ([Verdict.ALLOW, Verdict.ASK, Verdict.DENY], Verdict.DENY),
        ([Verdict.DENY, Verdict.ALLOW], Verdict.DENY),
        ([Verdict.ALLOW, Verdict.ASK], Verdict.ASK),
        ([Verdict.ASK, Verdict.ALLOW, Verdict.ALLOW], Verdict.ASK),
        ([Verdict.ALLOW, Verdict.ALLOW], Verdict.ALLOW),
    ],
)
def test_ac_002_most_restrictive_verdict_wins(verdicts: list[Verdict], expected: Verdict) -> None:
    findings = [_f(v, Tier.T0, f"r{i}") for i, v in enumerate(verdicts)]

    decision = combine(findings, HASH)

    assert decision.verdict is expected


def test_ac_002_highest_tier_wins() -> None:
    findings = [
        _f(Verdict.ALLOW, Tier.T0, "a"),
        _f(Verdict.ASK, Tier.T2, "b"),
        _f(Verdict.ALLOW, Tier.T1, "c"),
    ]

    decision = combine(findings, HASH)

    assert decision.tier is Tier.T2


def test_ac_002_reasons_and_rules_of_the_winning_verdict_come_first() -> None:
    findings = [_f(Verdict.ALLOW, Tier.T0, "read_only"), _f(Verdict.DENY, Tier.T3, "sql_drop")]

    decision = combine(findings, HASH)

    assert decision.rule_ids[0] == "sql_drop"
    assert decision.reasons[0] == "because sql_drop"


def test_ac_002_no_findings_means_deny() -> None:
    decision = combine([], HASH)

    assert decision.verdict is Verdict.DENY


def test_ac_001_allowed_is_true_only_for_allow(gate: Gate) -> None:
    allowed = gate.decide(make_call("read_file", {"path": "a.txt"}), make_session())
    denied = gate.decide(make_call("magic.tool", {}), make_session())

    assert (allowed.allowed, denied.allowed) == (True, False)
