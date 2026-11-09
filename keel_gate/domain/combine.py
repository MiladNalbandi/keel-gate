"""Combine findings into one Decision: the most restrictive verdict and the highest tier win (AC-002)."""

from __future__ import annotations

from collections.abc import Sequence

from keel_gate.domain.models import Decision, Finding, Tier, Verdict


def message_for(verdict: Verdict, reason: str) -> str:
    """The text the model receives when its call does not run."""
    if verdict is Verdict.DENY:
        return (
            f"keel-gate blocked this call: {reason}. Do not retry it in another form; stop and ask the user what to do."
        )
    if verdict in (Verdict.ASK, Verdict.DEFER):
        return f"keel-gate needs a human to approve this call: {reason}. Wait for the approval or ask the user."
    return ""


def combine(findings: Sequence[Finding], call_hash: str) -> Decision:
    """No findings means nobody vouched for the call, so it is denied (fail closed)."""
    if not findings:
        reason = "no rule decided this call"
        return Decision(
            Verdict.DENY,
            Tier.T3,
            (reason,),
            ("no_decision",),
            call_hash,
            message_for(Verdict.DENY, reason),
        )

    ordered = sorted(findings, key=lambda f: (-f.verdict.rank, -f.tier.rank))
    verdict = ordered[0].verdict
    tier = max((f.tier for f in findings), key=lambda t: t.rank)
    reasons = tuple(dict.fromkeys(f.reason for f in ordered))
    rule_ids = tuple(dict.fromkeys(f.rule_id for f in ordered))
    return Decision(verdict, tier, reasons, rule_ids, call_hash, message_for(verdict, reasons[0]))
