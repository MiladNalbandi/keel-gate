"""Versioned rules and tools that humans manage (Amendment A2, AC-190 to AC-199).

Every change makes a new version with a record (who, when, before, after) and tells subscribers (the gate) at once,
so the change applies to the next decision. Any version can be restored in one step. With policy_changes = "git",
every change is refused: the files are the only way.

This class keeps state in memory. The Gate Service persists it to policies/custom.yaml and SQLite (infra layer).
Who may call it (policy admins with a fresh step-up) is checked by the server before it gets here (AC-195).
"""

from __future__ import annotations

import copy
import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from keel_gate.domain.canonical import canonical_json, sha256_hex
from keel_gate.domain.draft import Draft
from keel_gate.domain.manifest import Manifest
from keel_gate.domain.rules import CustomRule
from keel_gate.gate import PolicyChanges, utc_now


class GitOnlyError(PermissionError):
    """Policy changes are set to git-only (AC-198)."""


class RuleNotFoundError(LookupError):
    pass


class ToolNotFoundError(LookupError):
    pass


class VersionNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class Change:
    version: int
    by: str
    at: datetime
    summary: str
    before: Mapping[str, Any] | None
    after: Mapping[str, Any] | None
    policy_hash: str


@dataclass(frozen=True)
class PolicySnapshot:
    version: int
    manifest: Manifest
    rules: tuple[CustomRule, ...]


@dataclass(frozen=True)
class RuleView:
    rule: CustomRule
    expired: bool


@dataclass(frozen=True)
class _Policy:
    rules: tuple[CustomRule, ...]
    tools: Mapping[str, Mapping[str, Any]]
    pins: Mapping[str, str]

    def hash(self) -> str:
        return sha256_hex(
            canonical_json(
                {"rules": [r.to_mapping() for r in self.rules], "tools": dict(self.tools), "pins": dict(self.pins)}
            )
        )


_UNSET: Any = object()


def _new_rule_id() -> str:
    return "ru_" + secrets.token_hex(5)


def _describe(rule: CustomRule) -> str:
    what = f"{rule.verdict} {rule.tool}" + (f' "{rule.match}"' if rule.match else "")
    return what + (f" when {rule.match_arg} matches" if rule.match_arg else "")


class PolicyStore:
    def __init__(
        self,
        tools: Mapping[str, Mapping[str, Any]],
        *,
        rules: Sequence[CustomRule] = (),
        pins: Mapping[str, str] | None = None,
        policy_changes: PolicyChanges = "ui",
        clock: Callable[[], datetime] = utc_now,
        new_id: Callable[[], str] = _new_rule_id,
    ) -> None:
        copied = copy.deepcopy(dict(tools))
        resolved_pins = dict(pins) if pins is not None else Manifest.from_mapping(copied).pins
        self.policy_changes = policy_changes
        self.clock = clock
        self.new_id = new_id
        self._manifest = Manifest.from_mapping(copied, pins=resolved_pins)
        self._history: dict[int, _Policy] = {0: _Policy(tuple(rules), copied, resolved_pins)}
        self._changes: list[Change] = []
        self._subscribers: list[Callable[[PolicySnapshot], None]] = []
        self._version = 0

    # ------------------------------------------------------------------ reading

    @property
    def version(self) -> int:
        return self._version

    @property
    def _current(self) -> _Policy:
        return self._history[self._version]

    @property
    def rules(self) -> tuple[CustomRule, ...]:
        return self._current.rules

    @property
    def manifest(self) -> Manifest:
        return self._manifest

    def snapshot(self) -> PolicySnapshot:
        return PolicySnapshot(self._version, self.manifest, self.rules)

    def list_rules(self) -> list[RuleView]:
        now = self.clock()
        return [RuleView(rule, rule.expired(now)) for rule in self.rules]

    def versions(self) -> list[Change]:
        """Newest first."""
        return list(reversed(self._changes))

    def subscribe(self, listener: Callable[[PolicySnapshot], None]) -> None:
        self._subscribers.append(listener)

    # ------------------------------------------------------------------ rules

    def add_rule(
        self,
        *,
        by: str,
        tool: str,
        verdict: str,
        reason: str,
        match: str | None = None,
        match_arg: str | None = None,
        expires_at: datetime | None = None,
    ) -> CustomRule:
        self._guard()
        rule = CustomRule.create(
            id=self.new_id(),
            tool=tool,
            verdict=verdict,
            reason=reason,
            match=match,
            match_arg=match_arg,
            expires_at=expires_at,
            created_by=by,
            created_at=self.clock(),
        )
        policy = self._current
        self._commit(replace(policy, rules=(*policy.rules, rule)), by, f"Added: {_describe(rule)}", None, rule)
        return rule

    def update_rule(
        self,
        rule_id: str,
        *,
        by: str,
        enabled: bool | None = None,
        verdict: str | None = None,
        reason: str | None = None,
        match: str | None = _UNSET,
        expires_at: datetime | None = _UNSET,
    ) -> CustomRule:
        self._guard()
        old = self._find_rule(rule_id)
        fields = old.to_mapping()
        fields["expires_at"] = old.expires_at
        fields["created_at"] = old.created_at
        if enabled is not None:
            fields["enabled"] = enabled
        if verdict is not None:
            fields["verdict"] = verdict
        if reason is not None:
            fields["reason"] = reason
        if match is not _UNSET:
            fields["match"] = match
        if expires_at is not _UNSET:
            fields["expires_at"] = expires_at
        new = CustomRule.create(**fields)
        policy = self._current
        rules = tuple(new if r.id == rule_id else r for r in policy.rules)
        if enabled is not None and new.enabled != old.enabled:
            summary = f"Switched {'on' if new.enabled else 'off'}: {_describe(new)}"
        else:
            summary = f"Changed: {_describe(new)}"
        self._commit(replace(policy, rules=rules), by, summary, old, new)
        return new

    def remove_rule(self, rule_id: str, *, by: str) -> None:
        self._guard()
        old = self._find_rule(rule_id)
        policy = self._current
        rules = tuple(r for r in policy.rules if r.id != rule_id)
        self._commit(replace(policy, rules=rules), by, f"Removed: {_describe(old)}", old, None)

    # ------------------------------------------------------------------ tools

    def import_tools(self, draft: Draft, *, by: str) -> list[str]:
        """Add drafted tools. They stay unpinned (not reviewed) until a human pins them (AC-193)."""
        self._guard()
        policy = self._current
        tools = {**copy.deepcopy(dict(policy.tools)), **copy.deepcopy(draft.tools)}
        names = sorted(draft.tools)
        summary = f"Imported {len(names)} draft tool(s): {', '.join(names)}"
        self._commit(replace(policy, tools=tools), by, summary, None, {"tools": names})
        return names

    def pin_tool(self, name: str, *, by: str) -> None:
        self._guard()
        policy = self._current
        if name not in policy.tools:
            raise ToolNotFoundError(name)
        pin = Manifest.from_mapping({name: policy.tools[name]}).pin_of(name)
        pins = {**dict(policy.pins), name: pin}
        before = {"pin": policy.pins.get(name)}
        self._commit(replace(policy, pins=pins), by, f"Pinned tool {name}", before, {"pin": pin})

    def remove_tool(self, name: str, *, by: str) -> None:
        self._guard()
        policy = self._current
        if name not in policy.tools:
            raise ToolNotFoundError(name)
        tools = {k: v for k, v in policy.tools.items() if k != name}
        pins = {k: v for k, v in policy.pins.items() if k != name}
        before = {"tool": name, **copy.deepcopy(dict(policy.tools[name]))}
        self._commit(_Policy(policy.rules, tools, pins), by, f"Removed tool {name}", before, None)

    # ------------------------------------------------------------------ versions

    def rollback(self, version: int, *, by: str) -> Change:
        self._guard()
        if version not in self._history:
            raise VersionNotFoundError(f"version {version} does not exist")
        target = self._history[version]
        before = {"version": self._version}
        return self._commit(target, by, f"Rolled back to version {version}", before, {"version": version})

    # ------------------------------------------------------------------ internals

    def _guard(self) -> None:
        if self.policy_changes == "git":
            raise GitOnlyError("policy changes are set to git only: edit policies/ in a reviewed change")

    def _find_rule(self, rule_id: str) -> CustomRule:
        for rule in self._current.rules:
            if rule.id == rule_id:
                return rule
        raise RuleNotFoundError(rule_id)

    def _commit(
        self,
        policy: _Policy,
        by: str,
        summary: str,
        before: CustomRule | Mapping[str, Any] | None,
        after: CustomRule | Mapping[str, Any] | None,
    ) -> Change:
        manifest = Manifest.from_mapping(policy.tools, pins=policy.pins)  # refuse a change that cannot load
        self._version += 1
        self._history[self._version] = policy
        self._manifest = manifest
        change = Change(
            version=self._version,
            by=by,
            at=self.clock(),
            summary=summary,
            before=before.to_mapping() if isinstance(before, CustomRule) else before,
            after=after.to_mapping() if isinstance(after, CustomRule) else after,
            policy_hash=policy.hash(),
        )
        self._changes.append(change)
        snapshot = self.snapshot()
        for listener in self._subscribers:
            listener(snapshot)
        return change
