"""Core value types. Pure data: no I/O, no clock, no framework imports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from functools import cached_property
from typing import Any

from keel_gate.domain.canonical import call_hash


class Verdict(StrEnum):
    """The OWASP Agent Control Standard answers (ADR 0006)."""

    ALLOW = "allow"
    MODIFY = "modify"
    ASK = "ask"
    DEFER = "defer"
    DENY = "deny"

    @property
    def rank(self) -> int:
        """Higher is more restrictive. The most restrictive verdict wins (AC-002)."""
        return _VERDICT_RANK[self]


_VERDICT_RANK = {
    Verdict.ALLOW: 0,
    Verdict.MODIFY: 1,
    Verdict.ASK: 2,
    Verdict.DEFER: 3,
    Verdict.DENY: 4,
}


class Tier(StrEnum):
    """T0 read only · T1 can be undone · T2 hard to undo · T3 catastrophic."""

    T0 = "T0"
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"

    @property
    def rank(self) -> int:
        return int(self.value[1])


class Taint(StrEnum):
    UNTRUSTED = "untrusted"
    SECRET = "secret"  # noqa: S105 - a taint label, not a password


class Source(StrEnum):
    """Which framework sent the call. It never changes the decision, only the logs."""

    CLAUDE = "claude"
    OPENAI = "openai"
    MCP = "mcp"
    CLAUDE_CODE = "claude_code"
    AGENT_SDK = "agent_sdk"
    RAW = "raw"


@dataclass(frozen=True)
class ToolCall:
    """One request from the model to run a tool, in keel-gate's own shape."""

    tool: str
    args: Mapping[str, Any]
    source: Source = Source.RAW

    @cached_property
    def call_hash(self) -> str:
        """Raises ValueError when the args cannot be hashed (for example NaN); the gate turns that into a deny."""
        return call_hash(self.tool, self.args)


@dataclass(frozen=True)
class Session:
    """One agent run. Who acts comes from here, never from tool arguments (AC-080)."""

    session_id: str
    agent_id: str
    on_behalf_of: str | None = None
    workspace: str | None = None
    taint: frozenset[Taint] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class Finding:
    """What one check says about a call. The gate combines all findings into one Decision."""

    verdict: Verdict
    tier: Tier
    rule_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class Decision:
    """The gate's answer for one call (AC-001)."""

    verdict: Verdict
    tier: Tier
    reasons: tuple[str, ...]
    rule_ids: tuple[str, ...]
    call_hash: str
    message_for_model: str = ""
    observed_verdict: Verdict | None = None

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.ALLOW
