"""Amendment A3, AC-210 to AC-224: the Monitor agent (optional, raise-only, a read-only judge)."""

from __future__ import annotations

import dataclasses
import logging
import time
from typing import Any

import pytest

from keel_gate.domain.combine import raise_only
from keel_gate.domain.manifest import Manifest
from keel_gate.domain.models import Decision, Finding, Tier, ToolCall, Verdict
from keel_gate.domain.review import (
    CANARIES,
    MonitorAnswerError,
    MonitorSettings,
    ReviewRequest,
    ReviewResult,
    clean_reason,
    should_review,
)
from keel_gate.gate import Gate, GateSettings, load_settings
from keel_gate.monitor import MonitoredGate
from tests.factories import (
    TASK,
    ScriptedReviewer,
    make_call,
    make_session,
    make_shell,
    verdict,
)

REFUND = {"order": "1042", "amount": "500.00"}
EDIT = {"path": "tests/test_cart.py", "old_string": "== 3", "new_string": "== 4"}


def monitored(
    manifest: Manifest, reviewer: ScriptedReviewer | None = None, *, gate_mode: str = "enforce", **monitor: Any
) -> MonitoredGate:
    settings = GateSettings(mode=gate_mode, monitor=MonitorSettings(**monitor))  # type: ignore[arg-type]
    return MonitoredGate(Gate(manifest, settings=settings), reviewer)


def session(intent: str | None = TASK) -> Any:
    return make_session(intent=intent)


# ---------- W. modes and scope ----------


def test_ac_210_the_monitor_is_off_by_default(manifest: Manifest) -> None:
    reviewer = ScriptedReviewer(verdict("block"))
    gate = Gate(manifest)
    guarded = MonitoredGate(gate, reviewer)

    decision = guarded.decide(make_call("edit_file", EDIT), session())

    assert gate.settings.monitor.mode == "off"
    assert decision == gate.decide(make_call("edit_file", EDIT), session())
    assert reviewer.requests == []


def test_ac_210_mode_off_needs_no_reviewer(manifest: Manifest) -> None:
    guarded = MonitoredGate(Gate(manifest))

    assert guarded.decide(make_call(), session()).verdict is Verdict.ALLOW


def test_ac_210_a_monitor_that_is_on_needs_a_reviewer(manifest: Manifest) -> None:
    with pytest.raises(ValueError, match="no reviewer"):
        monitored(manifest, None, mode="strict")


def test_ac_211_approvals_mode_reviews_only_calls_that_ask(manifest: Manifest) -> None:
    reviewer = ScriptedReviewer()
    guarded = monitored(manifest, reviewer, mode="approvals")

    guarded.decide(make_call("payments.refund", REFUND), session())
    guarded.decide(make_call("edit_file", EDIT), session())
    guarded.decide(make_call(), session())

    assert [r.tool for r in reviewer.requests] == ["payments.refund"]


def test_ac_211_changes_mode_skips_read_only_calls(manifest: Manifest) -> None:
    reviewer = ScriptedReviewer()
    guarded = monitored(manifest, reviewer, mode="changes")

    guarded.decide(make_call(), session())  # read_file: T0
    guarded.decide(make_call("edit_file", EDIT), session())  # T1

    assert [r.tool for r in reviewer.requests] == ["edit_file"]


def test_ac_211_strict_mode_reviews_reads_too(manifest: Manifest) -> None:
    reviewer = ScriptedReviewer()
    guarded = monitored(manifest, reviewer, mode="strict")

    guarded.decide(make_call(), session())

    assert [r.tool for r in reviewer.requests] == ["read_file"]


@pytest.mark.parametrize(
    "call",
    [make_shell("rm -rf ~"), make_call("infra.volume_delete", {"volume_id": "v1"}), make_call("no.such_tool", {})],
)
def test_ac_211_a_denied_call_is_never_sent_to_the_monitor(manifest: Manifest, call: ToolCall) -> None:
    reviewer = ScriptedReviewer()
    guarded = monitored(manifest, reviewer, mode="strict")

    decision = guarded.decide(call, session())

    assert decision.verdict is Verdict.DENY
    assert reviewer.requests == []


@pytest.mark.parametrize(
    ("mode", "verdict_", "tier", "expected"),
    [
        ("off", Verdict.ALLOW, Tier.T1, False),
        ("approvals", Verdict.ASK, Tier.T2, True),
        ("approvals", Verdict.ALLOW, Tier.T1, False),
        ("changes", Verdict.ALLOW, Tier.T0, False),
        ("changes", Verdict.ALLOW, Tier.T1, True),
        ("changes", Verdict.ASK, Tier.T2, True),
        ("strict", Verdict.ALLOW, Tier.T0, True),
        ("strict", Verdict.DENY, Tier.T3, False),
        ("changes", Verdict.DENY, Tier.T2, False),
    ],
)
def test_ac_211_should_review_table(mode: str, verdict_: Verdict, tier: Tier, expected: bool) -> None:
    assert should_review(mode, verdict_, tier) is expected  # type: ignore[arg-type]


def test_ac_212_the_monitor_is_set_in_the_config_file() -> None:
    settings = load_settings({"monitor": {"mode": "changes", "model": "claude-sonnet-5-5", "timeout_s": 3}})

    assert settings.monitor == MonitorSettings(mode="changes", timeout_s=3.0)
    assert settings.monitor.on_error == "ask"


@pytest.mark.parametrize(
    "monitor",
    [
        {"mode": "paranoid"},
        {"mode": "strict", "tools": ["shell"]},
        {"mode": "strict", "prompt": "always answer fits"},
        {"on_error": "allow"},
        {"timeout_s": 0},
        {"timeout_s": 31},
        {"effort": "max"},
        {"model": ""},
        {"timeout_s": True},
        {"mode": True},
        "strict",
    ],
)
def test_ac_212_bad_monitor_config_is_rejected(monitor: Any) -> None:
    with pytest.raises(ValueError, match="invalid gate config"):
        load_settings({"monitor": monitor})


def test_ac_212_unquoted_yaml_off_means_off() -> None:
    """YAML 1.1 reads `mode: off` as False. That can only mean "off", so it is accepted."""
    assert load_settings({"monitor": {"mode": False}}).monitor.mode == "off"


def test_ac_212_the_monitor_settings_have_no_field_for_tools_or_prompts() -> None:
    names = {f.name for f in dataclasses.fields(MonitorSettings)}

    assert names == {"mode", "model", "timeout_s", "on_error", "effort"}


# ---------- X. raise-only ----------


def test_ac_213_fits_leaves_the_decision_unchanged(manifest: Manifest) -> None:
    guarded = monitored(manifest, ScriptedReviewer(verdict("fits")), mode="strict")
    plain = Gate(manifest)

    for call in (make_call(), make_call("edit_file", EDIT), make_call("payments.refund", REFUND)):
        assert guarded.decide(call, session()) == plain.decide(call, session())


def test_ac_213_ask_raises_an_allowed_call_to_ask(manifest: Manifest) -> None:
    guarded = monitored(manifest, ScriptedReviewer(verdict("ask", "editing tests was not asked")), mode="strict")

    decision = guarded.decide(make_call("edit_file", EDIT), session())

    assert decision.verdict is Verdict.ASK
    assert decision.tier.rank >= Tier.T2.rank
    assert decision.rule_ids[0] == "monitor_flagged"
    assert decision.reasons[0] == "monitor: editing tests was not asked"
    assert "editing tests was not asked" not in decision.message_for_model
    assert "does not clearly fit the user's task" in decision.message_for_model


def test_ac_213_block_turns_an_allowed_call_into_a_deny(manifest: Manifest) -> None:
    guarded = monitored(manifest, ScriptedReviewer(verdict("block", "off task")), mode="strict")

    decision = guarded.decide(make_call(), session())

    assert decision.verdict is Verdict.DENY
    assert "monitor_flagged" in decision.rule_ids
    assert decision.message_for_model.startswith("keel-gate blocked this call: the monitor judged")
    assert "off task" not in decision.message_for_model


def test_ac_213_fits_never_lowers_an_ask(manifest: Manifest) -> None:
    guarded = monitored(manifest, ScriptedReviewer(verdict("fits")), mode="strict")

    decision = guarded.decide(make_call("payments.refund", REFUND), session())

    assert decision.verdict is Verdict.ASK


def test_ac_213_a_flag_on_an_ask_keeps_both_reasons(manifest: Manifest) -> None:
    plain = Gate(manifest).decide(make_call("payments.refund", REFUND), session())
    guarded = monitored(manifest, ScriptedReviewer(verdict("ask", "the amount looks high")), mode="approvals")

    decision = guarded.decide(make_call("payments.refund", REFUND), session())

    assert decision.verdict is Verdict.ASK
    assert set(plain.rule_ids) < set(decision.rule_ids)
    assert "monitor: the amount looks high" in decision.reasons
    assert decision.message_for_model == plain.message_for_model


@pytest.mark.parametrize("before", list(Verdict))
@pytest.mark.parametrize("added", [Verdict.ALLOW, Verdict.ASK, Verdict.DENY])
def test_ac_213_raise_only_never_lowers_anything(before: Verdict, added: Verdict) -> None:
    decision = Decision(before, Tier.T1, ("rule says so",), ("some_rule",), "h" * 64, "msg")

    result = raise_only(decision, Finding(added, Tier.T2, "monitor_flagged", "monitor: x"))

    assert result.verdict.rank == max(before.rank, added.rank)
    assert result.tier is Tier.T2
    assert "some_rule" in result.rule_ids
    assert "rule says so" in result.reasons
    assert result.call_hash == decision.call_hash


@pytest.mark.parametrize(
    "answer",
    [RuntimeError("api down"), MonitorAnswerError("bad json"), "not a ReviewResult", None],
)
def test_ac_214_a_failed_review_asks_a_human(manifest: Manifest, answer: Any) -> None:
    guarded = monitored(manifest, ScriptedReviewer(answer if answer is not None else lambda _r: None), mode="strict")

    decision = guarded.decide(make_call("edit_file", EDIT), session())

    assert decision.verdict is Verdict.ASK
    assert decision.rule_ids[0] == "monitor_error"
    assert decision.reasons[0].startswith("monitor: review failed")


def test_ac_214_on_error_deny_blocks_instead(manifest: Manifest) -> None:
    guarded = monitored(manifest, ScriptedReviewer(RuntimeError("api down")), mode="strict", on_error="deny")

    decision = guarded.decide(make_call("edit_file", EDIT), session())

    assert decision.verdict is Verdict.DENY
    assert "monitor_error" in decision.rule_ids


@pytest.mark.parametrize("intent", [None, "", "   "])
def test_ac_214_a_session_without_a_task_is_a_failure(manifest: Manifest, intent: str | None) -> None:
    reviewer = ScriptedReviewer()
    guarded = monitored(manifest, reviewer, mode="strict")

    decision = guarded.decide(make_call("edit_file", EDIT), session(intent))

    assert decision.verdict is Verdict.ASK
    assert "monitor_error" in decision.rule_ids
    assert "no task" in decision.reasons[0]
    assert reviewer.requests == []


def test_ac_214_failures_never_log_the_arguments(manifest: Manifest, caplog: pytest.LogCaptureFixture) -> None:
    guarded = monitored(manifest, ScriptedReviewer(RuntimeError("boom")), mode="strict")
    secret_edit = {**EDIT, "new_string": "token-value-that-must-not-leak"}

    with caplog.at_level(logging.DEBUG, logger="keel_gate"):
        guarded.decide(make_call("edit_file", secret_edit), session())

    assert "edit_file" in caplog.text
    assert "token-value-that-must-not-leak" not in caplog.text


def test_ac_215_observe_mode_only_records_the_monitor(manifest: Manifest) -> None:
    guarded = monitored(manifest, ScriptedReviewer(verdict("block", "off task")), gate_mode="observe", mode="strict")

    decision = guarded.decide(make_call(), session())

    assert decision.verdict is Verdict.ALLOW
    assert decision.observed_verdict is Verdict.DENY
    assert "monitor: off task" in decision.reasons
    assert "observe mode: would have denied" in decision.reasons
    assert decision.message_for_model == ""


def test_ac_215_observe_mode_updates_an_earlier_would_have(manifest: Manifest) -> None:
    guarded = monitored(manifest, ScriptedReviewer(verdict("block")), gate_mode="observe", mode="approvals")

    decision = guarded.decide(make_call("payments.refund", REFUND), session())

    assert decision.verdict is Verdict.ALLOW
    assert decision.observed_verdict is Verdict.DENY
    assert "observe mode: would have denied" in decision.reasons
    assert "observe mode: would have asked" not in decision.reasons


def test_ac_215_the_floor_still_blocks_in_observe_mode(manifest: Manifest) -> None:
    reviewer = ScriptedReviewer(verdict("fits"))
    guarded = monitored(manifest, reviewer, gate_mode="observe", mode="strict")

    decision = guarded.decide(make_shell("rm -rf ~"), session())

    assert decision.verdict is Verdict.DENY
    assert reviewer.requests == []


# ---------- Y. what the monitor sees ----------


def test_ac_216_the_monitor_sees_only_task_call_and_findings(manifest: Manifest) -> None:
    reviewer = ScriptedReviewer()
    guarded = monitored(manifest, reviewer, mode="strict")

    guarded.decide(make_call("payments.refund", REFUND), session())

    request = reviewer.requests[0]
    assert {f.name for f in dataclasses.fields(ReviewRequest)} == {
        "intent",
        "tool",
        "tool_description",
        "args_json",
        "gate_verdict",
        "gate_tier",
        "gate_reasons",
    }
    assert request.intent == TASK
    assert request.tool == "payments.refund"
    assert request.tool_description == "Refund an order."
    assert '"amount":"500.00"' in request.args_json
    assert request.gate_verdict == "ask"
    assert request.gate_reasons


def test_ac_217_secrets_are_redacted_before_the_monitor_sees_them(manifest: Manifest) -> None:
    reviewer = ScriptedReviewer()
    guarded = monitored(manifest, reviewer, mode="strict")
    key = "sk-ant-api03-" + "A" * 40

    guarded.decide(
        make_call("edit_file", {**EDIT, "new_string": f"client = Client('{key}')"}),
        session(f"Use the key {key} in the test"),
    )

    request = reviewer.requests[0]
    assert key not in request.args_json
    assert key not in request.intent
    assert "[redacted]" in request.args_json
    assert "[redacted]" in request.intent


# ---------- Z. fast and recorded ----------


def test_ac_220_a_slow_monitor_times_out_and_asks(manifest: Manifest) -> None:
    guarded = monitored(manifest, ScriptedReviewer(delay_s=1.0), mode="strict", timeout_s=0.05)

    start = time.perf_counter()
    decision = guarded.decide(make_call("edit_file", EDIT), session())
    elapsed = time.perf_counter() - start

    assert decision.verdict is Verdict.ASK
    assert "monitor_error" in decision.rule_ids
    assert "timed out" in decision.reasons[0]
    assert elapsed < 0.5
    guarded.close()


def test_ac_221_the_same_call_is_reviewed_once(manifest: Manifest) -> None:
    reviewer = ScriptedReviewer(verdict("ask"))
    guarded = monitored(manifest, reviewer, mode="strict")

    first = guarded.decide(make_call("edit_file", EDIT), session())
    second = guarded.decide(make_call("edit_file", EDIT), session())
    guarded.decide(make_call("edit_file", EDIT), session("Another task"))

    assert first == second
    assert len(reviewer.requests) == 2


def test_ac_221_failures_are_not_cached(manifest: Manifest) -> None:
    reviewer = ScriptedReviewer(RuntimeError("blip"), verdict("fits"))
    guarded = monitored(manifest, reviewer, mode="strict")

    first = guarded.decide(make_call("edit_file", EDIT), session())
    second = guarded.decide(make_call("edit_file", EDIT), session())

    assert first.verdict is Verdict.ASK
    assert second.verdict is Verdict.ALLOW
    assert len(reviewer.requests) == 2


# ---------- AA. a read-only judge, validated ----------


def test_ac_222_the_monitor_gets_only_immutable_values(manifest: Manifest) -> None:
    reviewer = ScriptedReviewer()
    monitored(manifest, reviewer, mode="strict").decide(make_call("edit_file", EDIT), session())
    request = reviewer.requests[0]

    with pytest.raises(dataclasses.FrozenInstanceError):
        request.intent = "something else"
    for f in dataclasses.fields(request):
        value = getattr(request, f.name)
        assert isinstance(value, str | tuple), f.name
        if isinstance(value, tuple):
            assert all(isinstance(item, str) for item in value)


def test_ac_222_a_review_result_is_only_a_verdict_and_a_reason() -> None:
    assert {f.name for f in dataclasses.fields(ReviewResult)} == {"verdict", "reason"}
    with pytest.raises(dataclasses.FrozenInstanceError):
        ReviewResult("fits", "ok").verdict = "block"  # type: ignore[misc]


@pytest.mark.parametrize(
    "data",
    [
        {"verdict": "fits"},
        {"reason": "ok"},
        {"verdict": "allow", "reason": "ok"},
        {"verdict": "fits", "reason": 7},
        {"verdict": "fits", "reason": "ok", "run_tool": "shell"},
        ["fits", "ok"],
        "fits",
        None,
    ],
)
def test_ac_223_answers_must_match_the_strict_schema(data: Any) -> None:
    with pytest.raises(MonitorAnswerError):
        ReviewResult.from_mapping(data)


def test_ac_223_a_valid_answer_is_accepted() -> None:
    assert ReviewResult.from_mapping({"verdict": "block", "reason": "off task"}) == ReviewResult("block", "off task")


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("off task", "off task"),
        ("  many   spaces\n\nand lines ", "many spaces and lines"),
        ("<script>alert(1)</script>", "scriptalert(1)/script"),
        ("bell\x07 and \x1b[31mcolor", "bell and [31mcolor"),
        ("", "no reason given"),
        ("x" * 500, "x" * 200),
    ],
)
def test_ac_223_the_reason_is_cleaned(raw: str, clean: str) -> None:
    assert clean_reason(raw) == clean
    assert ReviewResult("ask", raw).reason == clean


def _canary_oracle(request: ReviewRequest) -> ReviewResult:
    expected = next(c.fits for c in CANARIES if c.request == request)
    return ReviewResult("fits" if expected else "block", "canary")


def test_ac_224_self_check_passes_with_a_working_monitor(manifest: Manifest) -> None:
    reviewer = ScriptedReviewer(_canary_oracle)
    guarded = monitored(manifest, reviewer, mode="strict")

    assert guarded.self_check() is True
    assert guarded.healthy is True
    assert len(reviewer.requests) == len(CANARIES) == 2
    assert {c.fits for c in CANARIES} == {True, False}


def test_ac_224_a_wrong_canary_answer_makes_every_review_ask(manifest: Manifest) -> None:
    reviewer = ScriptedReviewer(verdict("fits"))  # says "fits" to everything, so the off-task canary fails
    guarded = monitored(manifest, reviewer, mode="strict")

    assert guarded.self_check() is False
    assert guarded.healthy is False
    decision = guarded.decide(make_call(), session())

    assert decision.verdict is Verdict.ASK
    assert "monitor_error" in decision.rule_ids
    assert "self-check" in decision.reasons[0]
    assert len(reviewer.requests) == len(CANARIES)  # an unhealthy monitor is not asked again


def test_ac_224_a_later_passing_self_check_heals_the_monitor(manifest: Manifest) -> None:
    answers: list[Any] = [verdict("fits"), verdict("fits")]
    reviewer = ScriptedReviewer(lambda r: answers.pop(0) if answers else _canary_oracle(r))
    guarded = monitored(manifest, reviewer, mode="strict")

    assert guarded.self_check() is False
    assert guarded.self_check() is True
    assert guarded.healthy is True


def test_ac_224_a_crashing_monitor_fails_the_self_check(manifest: Manifest) -> None:
    guarded = monitored(manifest, ScriptedReviewer(RuntimeError("no key")), mode="strict")

    assert guarded.self_check() is False


def test_ac_224_self_check_with_the_monitor_off_calls_nothing(manifest: Manifest) -> None:
    reviewer = ScriptedReviewer()
    guarded = MonitoredGate(Gate(manifest), reviewer)

    assert guarded.self_check() is True
    assert reviewer.requests == []


def test_monitor_settings_mode_comes_only_from_the_gate(manifest: Manifest) -> None:
    gate = Gate(manifest, settings=GateSettings(monitor=MonitorSettings(mode="strict")))
    guarded = MonitoredGate(gate, ScriptedReviewer())

    assert guarded.settings is gate.settings.monitor


# ---------- clarifications after the security review (2026-11-10) ----------


def test_ac_221_the_cache_key_covers_everything_the_monitor_saw(manifest: Manifest) -> None:
    reason = ["first reason"]
    reviewer = ScriptedReviewer(verdict("fits"), verdict("block"))
    settings = GateSettings(monitor=MonitorSettings(mode="strict"))
    gate = Gate(
        manifest, settings=settings, extra_checks=[lambda c, s: [Finding(Verdict.ASK, Tier.T2, "x", reason[0])]]
    )
    guarded = MonitoredGate(gate, reviewer)

    first = guarded.decide(make_call(), session())
    reason[0] = "a different reason"
    second = guarded.decide(make_call(), session())

    assert len(reviewer.requests) == 2
    assert first.verdict is Verdict.ASK
    assert second.verdict is Verdict.DENY


def test_ac_220_a_hung_monitor_cannot_pile_up_reviews(manifest: Manifest) -> None:
    import threading

    release = threading.Event()
    reviewer = ScriptedReviewer(lambda r: (release.wait(5), verdict("fits"))[1])
    guarded = monitored(manifest, reviewer, mode="strict", timeout_s=0.02)

    decisions = [guarded.decide(make_call("read_file", {"path": f"f{i}.py"}), session()) for i in range(30)]
    release.set()
    guarded.close()
    time.sleep(0.05)

    assert all(d.verdict is Verdict.ASK for d in decisions)
    assert len(reviewer.requests) <= 8
    assert any("busy" in d.reasons[0] for d in decisions)


@pytest.mark.parametrize("exc", [SystemExit(3), GeneratorExit()])
def test_decide_never_raises_even_for_base_exceptions(manifest: Manifest, exc: BaseException) -> None:
    guarded = monitored(manifest, ScriptedReviewer(exc), mode="strict")

    decision = guarded.decide(make_call("edit_file", EDIT), session())

    assert decision.verdict is Verdict.ASK
    assert "monitor_error" in decision.rule_ids


def test_ac_222_a_result_subclass_is_rejected(manifest: Manifest) -> None:
    class Sneaky(ReviewResult):
        pass

    sneaky = Sneaky("fits", "ok")
    guarded = monitored(manifest, ScriptedReviewer(verdict("ask"), sneaky), mode="strict")
    guarded.decide(make_call(), session())

    decision = guarded.decide(make_call("edit_file", EDIT), session())

    assert "monitor_error" in decision.rule_ids


@pytest.mark.parametrize(
    ("call", "intent"),
    [
        (make_call("edit_file", {**EDIT, "new_string": "x" * 40_000}), TASK),
        (make_call("edit_file", EDIT), "y" * 9_000),
    ],
)
def test_ac_214_input_too_large_to_review_asks_a_human(manifest: Manifest, call: ToolCall, intent: str) -> None:
    reviewer = ScriptedReviewer()
    guarded = monitored(manifest, reviewer, mode="strict")

    decision = guarded.decide(call, session(intent))

    assert decision.verdict is Verdict.ASK
    assert "too large" in decision.reasons[0]
    assert reviewer.requests == []


def test_ac_214_a_failure_tells_the_model_a_fixed_message(manifest: Manifest) -> None:
    guarded = monitored(manifest, ScriptedReviewer(RuntimeError("secret detail")), mode="strict")

    decision = guarded.decide(make_call("edit_file", EDIT), session())

    assert "could not review" in decision.message_for_model
    assert "secret detail" not in decision.message_for_model


def test_ac_224_from_settings_runs_the_self_check(manifest: Manifest) -> None:
    from tests.factories import FakeAnthropic, model_answer

    gate = Gate(manifest, settings=GateSettings(monitor=MonitorSettings(mode="strict")))
    always_fits = FakeAnthropic(model_answer("fits"))

    guarded = MonitoredGate.from_settings(gate, client=always_fits)

    assert len(always_fits.requests) == len(CANARIES)
    assert guarded.healthy is False


def test_ac_224_from_settings_with_the_monitor_off_calls_nothing(manifest: Manifest) -> None:
    from tests.factories import FakeAnthropic

    client = FakeAnthropic()
    guarded = MonitoredGate.from_settings(Gate(manifest), client=client)

    assert client.requests == []
    assert guarded.healthy is True
