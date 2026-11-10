"""Combine findings into one Decision: the most restrictive verdict and the highest tier win (AC-002)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

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


def raise_only(decision: Decision, finding: Finding) -> Decision:
    """Add one later finding (for example the monitor's) to a decision. The answer can only get stricter (AC-213).

    A stricter finding leads: its reason comes first and the model is told about it. A finding that is not stricter
    is still recorded, but the verdict and the message stay as they were. Nothing is ever removed.
    """
    stricter = finding.verdict.rank > decision.verdict.rank
    tier = max(decision.tier, finding.tier, key=lambda t: t.rank)
    if stricter:
        reasons = tuple(dict.fromkeys((finding.reason, *decision.reasons)))
        rule_ids = tuple(dict.fromkeys((finding.rule_id, *decision.rule_ids)))
        return replace(
            decision,
            verdict=finding.verdict,
            tier=tier,
            reasons=reasons,
            rule_ids=rule_ids,
            message_for_model=message_for(finding.verdict, finding.reason),
        )
    return replace(
        decision,
        tier=tier,
        reasons=tuple(dict.fromkeys((*decision.reasons, finding.reason))),
        rule_ids=tuple(dict.fromkeys((*decision.rule_ids, finding.rule_id))),
    )
