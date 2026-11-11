"""The gate: one decide() per tool call, fail closed (AC-001 to AC-005, AC-091, AC-180 to AC-200).

Pipeline (each step can only make the answer stricter, except a custom allow, which can only remove an "ask"):
    hash → manifest lookup → pin check → schema check → built-in rules → custom rules → extra checks → combine
    → observe mode (keeps the safety floor)
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Literal, get_args

from keel_gate.domain.classify import DEFAULT_PROTECTED_BRANCHES, ShellContext, classify_tool_parts
from keel_gate.domain.combine import combine, message_for
from keel_gate.domain.manifest import Manifest, ManifestError
from keel_gate.domain.models import Decision, Finding, Session, Tier, ToolCall, Verdict
from keel_gate.domain.review import MonitorSettings
from keel_gate.domain.rules import CustomRule, RuleIndex, apply_rules
from keel_gate.domain.schema import validate

log = logging.getLogger("keel_gate")

Check = Callable[[ToolCall, Session], Sequence[Finding]]
Mode = Literal["enforce", "observe"]
PolicyChanges = Literal["ui", "git"]
_NO_HASH = "0" * 64

# Decisions that stay deny in observe mode, and that no custom allow rule can remove (AC-181, AC-197).
FLOOR_RULES = frozenset(
    {
        "rm_rf_dangerous",
        "disk_wipe",
        "sql_drop",
        "git_force_protected",
        "remote_destructive",
        "destructive_tool",
        "protected_path",
        "tool_pin_changed",
        "gate_error",
    }
)


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class GateSettings:
    mode: Mode = "enforce"
    time_budget_s: float = 0.2
    protected_branches: tuple[str, ...] = field(default=DEFAULT_PROTECTED_BRANCHES)
    protected_paths: tuple[str, ...] = ("policy", ".keel-gate", "keel-gate.yaml")
    # Host-supplied symlink snapshot: (absolute link path, canonical target).
    # Refresh it outside decide() when the workspace filesystem changes.
    path_aliases: tuple[tuple[str, str], ...] = ()
    policy_changes: PolicyChanges = "ui"
    monitor: MonitorSettings = field(default_factory=MonitorSettings)

    def __post_init__(self) -> None:
        if self.mode not in get_args(Mode):
            raise ValueError(f"invalid gate config: mode must be enforce or observe, not {self.mode!r}")
        if self.policy_changes not in get_args(PolicyChanges):
            raise ValueError("invalid gate config: policy_changes must be ui or git")
        if not 0 < self.time_budget_s <= 5:
            raise ValueError("invalid gate config: time_budget_s must be between 0 and 5 seconds")
        if not isinstance(self.monitor, MonitorSettings):
            raise ValueError("invalid gate config: monitor must be a monitor section")


_SETTING_KEYS = frozenset(
    {"mode", "time_budget_s", "protected_branches", "protected_paths", "path_aliases", "policy_changes", "monitor"}
)


def load_settings(config: Mapping[str, Any]) -> GateSettings:
    """Settings from the gate's config file (keel-gate.yaml). The modes can only come from here (AC-184, AC-212)."""
    if not isinstance(config, Mapping):
        raise ValueError("invalid gate config: it must be a mapping")
    unknown = set(config) - _SETTING_KEYS
    if unknown:
        raise ValueError(f"invalid gate config: unknown key(s) {', '.join(sorted(unknown))}")
    values = dict(config)
    if "protected_branches" in values:
        values["protected_branches"] = tuple(values["protected_branches"])
    if "protected_paths" in values:
        values["protected_paths"] = tuple(values["protected_paths"])
    if "path_aliases" in values:
        values["path_aliases"] = tuple(tuple(pair) for pair in values["path_aliases"])
    if "monitor" in values:
        values["monitor"] = MonitorSettings.from_mapping(values["monitor"])
    return GateSettings(**values)


@dataclass(frozen=True)
class _State:
    """Everything decide() reads, swapped as one object so a decision never sees half a change (AC-199)."""

    manifest: Manifest
    rules: RuleIndex


class Gate:
    def __init__(
        self,
        manifest: Manifest,
        *,
        settings: GateSettings | None = None,
        rules: Sequence[CustomRule] = (),
        extra_checks: Sequence[Check] = (),
        monotonic: Callable[[], float] = time.perf_counter,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.settings = settings or GateSettings()
        self.extra_checks = tuple(extra_checks)
        self._monotonic = monotonic
        self._clock = clock
        self._state = self._build(manifest, rules)

    def _build(self, manifest: Manifest, rules: Sequence[CustomRule]) -> _State:
        if manifest.draft and self.settings.mode != "observe":
            raise ManifestError(
                "this manifest is a draft: review it and set draft: false, or run the gate in observe mode"
            )
        return _State(manifest, RuleIndex(tuple(rules)))

    @property
    def manifest(self) -> Manifest:
        return self._state.manifest

    def apply(self, snapshot: Any) -> None:
        """Take a new policy snapshot (anything with .manifest and .rules). Applies to the next decision."""
        self._state = self._build(snapshot.manifest, snapshot.rules)

    def decide(self, call: ToolCall, session: Session) -> Decision:
        """Never raises. Any error, or going past the time budget, is a deny (ADR 0002)."""
        start = self._monotonic()
        state = self._state
        try:
            decision = self._decide(call, session, state)
        except Exception as exc:  # noqa: BLE001 - fail closed: every failure must become a deny
            log.error("keel-gate: decide failed for tool %r: %s", call.tool, type(exc).__name__)
            return _gate_error(call, "the safety check failed")
        if self._monotonic() - start > self.settings.time_budget_s:
            log.error("keel-gate: decide passed its time budget for tool %r", call.tool)
            return _gate_error(call, "time budget exceeded")
        if self.settings.mode == "observe":
            return _observe(decision)
        return decision

    def _decide(self, call: ToolCall, session: Session, state: _State) -> Decision:
        call_hash = call.call_hash
        spec = state.manifest.get(call.tool)
        if spec is None:
            return _single(
                Verdict.DENY, Tier.T3, "unknown_tool", f"tool '{call.tool}' is not in the manifest", call_hash
            )
        pin = state.manifest.pin_state(spec.name)
        if pin == "missing":
            return _single(
                Verdict.DENY,
                Tier.T3,
                "tool_not_reviewed",
                f"tool '{spec.name}' was added but a human has not reviewed and pinned it yet",
                call_hash,
            )
        if pin == "changed":
            return _single(
                Verdict.DENY,
                Tier.T3,
                "tool_pin_changed",
                f"tool '{spec.name}' changed since it was pinned; a human must review and re-pin it",
                call_hash,
            )
        errors = validate(call.args, spec.schema)
        if errors:
            return _single(
                Verdict.DENY,
                Tier.T2,
                "invalid_arguments",
                f"arguments do not match the tool's schema ({errors[0]})",
                call_hash,
            )
        ctx = ShellContext(
            workspace=session.workspace,
            protected_branches=self.settings.protected_branches,
            protected_paths=self.settings.protected_paths,
            path_aliases=self.settings.path_aliases,
        )
        classification = classify_tool_parts(spec, call.args, ctx)
        findings = apply_rules(state.rules, call, classification, self._clock)
        for check in self.extra_checks:
            findings.extend(check(call, session))
        return combine(findings, call_hash)


def is_floor(decision: Decision) -> bool:
    return decision.verdict is Verdict.DENY and any(rule in FLOOR_RULES for rule in decision.rule_ids)


def _observe(decision: Decision) -> Decision:
    """Observe mode: report what enforce would do, but only the safety floor really blocks (AC-181 to AC-183)."""
    if decision.verdict is Verdict.ALLOW or is_floor(decision):
        return decision
    would = "denied" if decision.verdict is Verdict.DENY else "asked"
    return replace(
        decision,
        verdict=Verdict.ALLOW,
        observed_verdict=decision.verdict,
        reasons=(*decision.reasons, f"observe mode: would have {would}"),
        message_for_model="",
    )


def _single(verdict: Verdict, tier: Tier, rule: str, reason: str, call_hash: str) -> Decision:
    return Decision(verdict, tier, (reason,), (rule,), call_hash, message_for(verdict, reason))


def _gate_error(call: ToolCall, kind: str) -> Decision:
    try:
        call_hash = call.call_hash
    except ValueError:
        call_hash = _NO_HASH
    reason = f"gate error: {kind}"
    return Decision(Verdict.DENY, Tier.T3, (reason,), ("gate_error",), call_hash, message_for(Verdict.DENY, reason))
