"""AC-004: any error or a blown time budget inside decide() means deny."""

from __future__ import annotations

from keel_gate.domain.manifest import Manifest
from keel_gate.domain.models import Finding, Session, ToolCall, Verdict
from keel_gate.gate import Gate, GateSettings
from tests.factories import make_call, make_session


def _boom(call: ToolCall, session: Session) -> list[Finding]:
    raise RuntimeError("bug in a check")


class _SlowClock:
    """A monotonic clock that jumps forward one second each time it is read."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 1.0
        return self.now


def test_ac_004_an_error_in_a_check_means_deny(manifest: Manifest) -> None:
    gate = Gate(manifest, extra_checks=[_boom])

    decision = gate.decide(make_call("read_file", {"path": "a.txt"}), make_session())

    assert decision.verdict is Verdict.DENY
    assert decision.reasons[0].startswith("gate error")


def test_ac_004_error_text_does_not_leak_internals(manifest: Manifest) -> None:
    gate = Gate(manifest, extra_checks=[_boom])

    decision = gate.decide(make_call("read_file", {"path": "a.txt"}), make_session())

    assert "bug in a check" not in " ".join(decision.reasons) + decision.message_for_model


def test_ac_004_blowing_the_time_budget_means_deny(manifest: Manifest) -> None:
    gate = Gate(manifest, settings=GateSettings(time_budget_s=0.5), monotonic=_SlowClock())

    decision = gate.decide(make_call("read_file", {"path": "a.txt"}), make_session())

    assert decision.verdict is Verdict.DENY
    assert decision.reasons[0].startswith("gate error: time budget")


def test_ac_004_args_that_cannot_be_hashed_mean_deny(gate: Gate) -> None:
    decision = gate.decide(ToolCall(tool="read_file", args={"path": float("nan")}), make_session())

    assert decision.verdict is Verdict.DENY


def test_ac_004_deny_explains_itself_to_the_model(gate: Gate) -> None:
    decision = gate.decide(make_call("magic.tool", {}), make_session())

    assert "blocked" in decision.message_for_model
