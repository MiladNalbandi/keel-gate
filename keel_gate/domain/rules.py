"""Custom rules that humans add, and the fast index the gate reads (Amendment A2, AC-190 to AC-200).

Speed: rules are compiled once, when the rule set changes, into an immutable index. Exact tool names are a dict
lookup; glob rules (`payments.*`) are matched once per tool name and cached. decide() never takes a lock: the gate
swaps in a whole new index in one step.

Safety: a custom allow rule removes only the "ask" findings of the command it matches. It never removes a deny (the
safety floor and protected paths are denies), and never a few asks that must always reach a human.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal, cast, get_args

from keel_gate.domain.canonical import canonical_json, sha256_hex
from keel_gate.domain.classify import Classification
from keel_gate.domain.models import Finding, Tier, ToolCall, Verdict

RuleVerdict = Literal["deny", "ask", "allow"]

_TOOL = re.compile(r"^[A-Za-z0-9_.:*?\[\]-]{1,200}$")
_ID = re.compile(r"^ru_[A-Za-z0-9_]{1,40}$")
_ARG = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_RULE_KEYS = frozenset(
    {"id", "tool", "verdict", "reason", "match", "match_arg", "enabled", "expires_at", "created_by", "created_at"}
)
NOT_SUPPRESSIBLE = frozenset({"privilege", "write_outside_workspace", "shell_dynamic_program"})


def _invalid(why: str) -> ValueError:
    return ValueError(f"invalid rule: {why}")


def _utc(value: datetime | date | str | None, name: str) -> datetime | None:
    if value is None or isinstance(value, datetime):
        moment = value
    elif isinstance(value, date):
        moment = datetime(value.year, value.month, value.day, tzinfo=UTC)
    elif isinstance(value, str):
        try:
            moment = datetime.fromisoformat(value)
        except ValueError as exc:
            raise _invalid(f"{name} is not an ISO date or time") from exc
    else:
        raise _invalid(f"{name} must be a date or time")
    if moment is not None and moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment


@dataclass(frozen=True)
class CustomRule:
    id: str
    tool: str
    verdict: RuleVerdict
    reason: str
    match: str | None = None
    match_arg: str | None = None
    enabled: bool = True
    expires_at: datetime | None = None
    created_by: str = ""
    created_at: datetime | None = None

    @classmethod
    def create(cls, **fields: Any) -> CustomRule:
        """Build a rule and check every field. Raises ValueError("invalid rule: …")."""
        unknown = set(fields) - _RULE_KEYS
        if unknown:
            raise _invalid(f"unknown field(s) {', '.join(sorted(unknown))}")
        rule_id = str(fields.get("id", ""))
        tool = fields.get("tool")
        verdict = fields.get("verdict")
        reason = fields.get("reason")
        match = fields.get("match") or None
        match_arg = fields.get("match_arg") or None
        enabled = fields.get("enabled", True)
        if not _ID.match(rule_id):
            raise _invalid("id must look like ru_<letters or digits>")
        if not isinstance(tool, str) or not _TOOL.match(tool):
            raise _invalid("tool must be a tool name or a glob such as payments.*")
        if verdict not in get_args(RuleVerdict):
            raise _invalid("verdict must be deny, ask, or allow")
        checked_verdict = cast(RuleVerdict, verdict)
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 300:
            raise _invalid("a reason (1 to 300 characters) is required")
        if match is not None and (not isinstance(match, str) or len(match) > 500):
            raise _invalid("match must be text of at most 500 characters")
        if match_arg is not None and (not isinstance(match_arg, str) or not _ARG.match(match_arg)):
            raise _invalid("match_arg must be an argument name")
        if not isinstance(enabled, bool):
            raise _invalid("enabled must be true or false")
        return cls(
            id=rule_id,
            tool=tool,
            verdict=checked_verdict,
            reason=reason.strip(),
            match=match,
            match_arg=match_arg,
            enabled=enabled,
            expires_at=_utc(fields.get("expires_at"), "expires_at"),
            created_by=str(fields.get("created_by", "")),
            created_at=_utc(fields.get("created_at"), "created_at"),
        )

    def expired(self, now: datetime) -> bool:
        return self.expires_at is not None and now >= self.expires_at

    def to_mapping(self) -> dict[str, Any]:
        """Plain data for the YAML file, change records, and the API."""
        return {
            "id": self.id,
            "tool": self.tool,
            "verdict": self.verdict,
            "reason": self.reason,
            "match": self.match,
            "match_arg": self.match_arg,
            "enabled": self.enabled,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


def rules_from_mapping(data: Mapping[str, Any]) -> list[CustomRule]:
    """Rules from parsed YAML: {"rules": [{tool, verdict, reason, ...}]}.

    A rule without an id gets a stable one.
    """
    if not isinstance(data, Mapping):
        raise _invalid("the rules file must be a mapping with a 'rules' list")
    items = data.get("rules") or []
    if not isinstance(items, list):
        raise _invalid("'rules' must be a list")
    rules: list[CustomRule] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise _invalid("each rule must be a mapping")
        fields = dict(item)
        fields.setdefault("id", "ru_" + sha256_hex(canonical_json({k: str(v) for k, v in fields.items()}))[:12])
        fields.setdefault("created_by", "file")
        rules.append(CustomRule.create(**fields))
    ids = [r.id for r in rules]
    if len(ids) != len(set(ids)):
        raise _invalid("two rules have the same id")
    return rules


@dataclass(frozen=True)
class _Compiled:
    rule: CustomRule
    pattern: re.Pattern[str] | None

    def matches(self, text: str | None, args: Mapping[str, Any]) -> bool:
        rule = self.rule
        if rule.match_arg is not None:
            value = args.get(rule.match_arg)
            if value is None:
                return False
            subject = value if isinstance(value, str) else canonical_json(value)
            return self.pattern is None or self.pattern.match(subject) is not None
        if self.pattern is None:
            return True
        subject = text if text is not None else canonical_json(dict(args))
        return self.pattern.match(subject) is not None


@dataclass
class RuleIndex:
    """Immutable after it is built (the cache only memoizes lookups)."""

    rules: tuple[CustomRule, ...] = ()
    _exact: dict[str, tuple[_Compiled, ...]] = field(default_factory=dict, init=False, repr=False)
    _globs: tuple[tuple[re.Pattern[str], _Compiled], ...] = field(default=(), init=False, repr=False)
    _cache: dict[str, tuple[_Compiled, ...]] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        exact: dict[str, list[_Compiled]] = {}
        globs: list[tuple[re.Pattern[str], _Compiled]] = []
        for rule in self.rules:
            if not rule.enabled:
                continue
            compiled = _Compiled(rule, re.compile(fnmatch.translate(rule.match)) if rule.match else None)
            if any(ch in rule.tool for ch in "*?["):
                globs.append((re.compile(fnmatch.translate(rule.tool)), compiled))
            else:
                exact.setdefault(rule.tool, []).append(compiled)
        self._exact = {name: tuple(items) for name, items in exact.items()}
        self._globs = tuple(globs)

    def for_tool(self, tool: str) -> tuple[_Compiled, ...]:
        hit = self._cache.get(tool)
        if hit is None:
            hit = self._exact.get(tool, ()) + tuple(c for pattern, c in self._globs if pattern.match(tool))
            if len(self._cache) < 10_000:
                self._cache[tool] = hit
        return hit


def apply_rules(
    index: RuleIndex, call: ToolCall, classification: Classification, now: Callable[[], datetime]
) -> list[Finding]:
    """Built-in findings, adjusted by the custom rules for this tool."""
    candidates = index.for_tool(call.tool)
    if not candidates:
        return classification.all()
    moment = now()
    active = [c for c in candidates if not c.rule.expired(moment)]
    if not active:
        return classification.all()
    out = list(classification.general)
    for unit in classification.units:
        matched = [c for c in active if c.matches(unit.text, call.args)]
        findings = list(unit.findings)
        allows = [c.rule for c in matched if c.rule.verdict == "allow"]
        if allows:
            findings = [f for f in findings if f.verdict is not Verdict.ASK or f.rule_id in NOT_SUPPRESSIBLE]
            findings.append(Finding(Verdict.ALLOW, Tier.T0, f"custom:{allows[0].id}", allows[0].reason))
        for c in matched:
            if c.rule.verdict == "deny":
                findings.append(Finding(Verdict.DENY, Tier.T2, f"custom:{c.rule.id}", c.rule.reason))
            elif c.rule.verdict == "ask":
                findings.append(Finding(Verdict.ASK, Tier.T2, f"custom:{c.rule.id}", c.rule.reason))
        out.extend(findings)
    return out
