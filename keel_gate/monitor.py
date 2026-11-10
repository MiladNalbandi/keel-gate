"""The Monitor agent step (Amendment A3, ADR 0012): an optional, raise-only, read-only judge after the rules.

    rules (Gate.decide, < 1 ms) ──► denied? stop ──► mode says review? ──► Reviewer (a model, no tools)
                                                                              │ fits / ask / block / failure
    final answer = the stricter of the two  ◄─────────────────────────────────┘

The Reviewer is a port: keel_gate/adapters/claude_monitor.py implements it with Claude. This module never imports a
model SDK, so a gate with the monitor off stays as fast and as small as before (AC-219).
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import replace
from typing import Any, Protocol

from keel_gate.domain.combine import message_for, raise_only
from keel_gate.domain.models import Decision, Finding, Session, ToolCall, Verdict
from keel_gate.domain.review import (
    CANARIES,
    FAILED_MESSAGE,
    FLAGGED_MESSAGE,
    MAX_ARGS_CHARS,
    MAX_INTENT_CHARS,
    MonitorSettings,
    ReviewRequest,
    ReviewResult,
    failure_finding,
    monitor_finding,
    review_request,
    should_review,
)
from keel_gate.gate import Gate, is_floor

log = logging.getLogger("keel_gate")

CACHE_SIZE = 1024
MAX_IN_FLIGHT = 8  # at most this many reviews run at once; more get "busy" (a failure: ask) instead of queueing
_WOULD_HAVE = "observe mode: would have "


class MonitorBusyError(RuntimeError):
    """All review slots are taken (for example by a hung model). The call gets the failure verdict at once."""


class Reviewer(Protocol):
    """Judges one call. Gets only immutable data; may return only a ReviewResult (AC-222)."""

    def review(self, request: ReviewRequest) -> ReviewResult: ...


_CacheKey = tuple[ReviewRequest, str, str, str]


class MonitoredGate:
    """A Gate plus the Monitor agent. Use it exactly like a Gate: decide() never raises and never runs a tool."""

    def __init__(self, gate: Gate, reviewer: Reviewer | None = None) -> None:
        self.gate = gate
        self.settings: MonitorSettings = gate.settings.monitor  # from the config file only (AC-212)
        if self.settings.mode != "off" and reviewer is None:
            raise ValueError("the monitor is on in the config, but no reviewer was given")
        self._reviewer = reviewer
        self._healthy = True
        self._cache: OrderedDict[_CacheKey, ReviewResult] = OrderedDict()
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(MAX_IN_FLIGHT)
        self._pool: ThreadPoolExecutor | None = None
        if self.settings.mode != "off":
            self._pool = ThreadPoolExecutor(max_workers=MAX_IN_FLIGHT, thread_name_prefix="keel-gate-monitor")

    @classmethod
    def from_settings(cls, gate: Gate, *, client: Any = None, run_self_check: bool = True) -> MonitoredGate:
        """The production entry point: the Claude reviewer from the config, checked with the canaries (AC-224)."""
        if gate.settings.monitor.mode == "off":
            return cls(gate)
        from keel_gate.adapters.claude_monitor import ClaudeReviewer  # imported only when the monitor is on

        guarded = cls(gate, ClaudeReviewer.from_settings(gate.settings.monitor, client=client))
        if run_self_check:
            guarded.self_check()
        return guarded

    @property
    def healthy(self) -> bool:
        return self._healthy

    def decide(self, call: ToolCall, session: Session) -> Decision:
        decision = self.gate.decide(call, session)
        if self.settings.mode == "off":
            return decision
        try:
            return self._monitor(call, session, decision)
        except Exception as exc:  # noqa: BLE001 - fail closed: a bug here must not become an allow
            log.error("keel-gate: the monitor step failed for tool %r: %s", call.tool, type(exc).__name__)
            return self._merge(decision, failure_finding(self.settings.on_error, "internal error"))

    def self_check(self) -> bool:
        """Run the canary cases (AC-224). A wrong or failed answer marks the monitor unhealthy until a check passes."""
        if self.settings.mode == "off":
            return True
        ok = True
        for canary in CANARIES:
            try:
                result = self._ask(canary.request)
            except Exception as exc:  # noqa: BLE001 - a crash is a failed check
                log.error("keel-gate: monitor self-check failed: %s", type(exc).__name__)
                ok = False
                continue
            if (result.verdict == "fits") is not canary.fits:
                log.error("keel-gate: monitor self-check failed: a canary got the wrong answer (%s)", result.verdict)
                ok = False
        self._healthy = ok
        if not ok:
            log.error("keel-gate: the monitor is unhealthy; every call it reviews gets the failure verdict")
        return ok

    def close(self) -> None:
        """Stop the worker thread. A review still running is abandoned; its call already got the failure verdict."""
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None

    # ---------- internals ----------

    def _monitor(self, call: ToolCall, session: Session, decision: Decision) -> Decision:
        effective = decision.observed_verdict or decision.verdict
        if not should_review(self.settings.mode, effective, decision.tier) or is_floor(decision):
            return decision
        finding = self._finding(call, session, decision)
        return decision if finding is None else self._merge(decision, finding)

    def _finding(self, call: ToolCall, session: Session, decision: Decision) -> Finding | None:
        on_error = self.settings.on_error
        if not self._healthy:
            return failure_finding(on_error, "the monitor failed its self-check")
        intent = (session.intent or "").strip()
        if not intent:
            return failure_finding(on_error, "no task (intent) was given for this session")
        spec = self.gate.manifest.get(call.tool)
        request = review_request(call, spec.description if spec else "", intent, decision)
        if len(request.args_json) > MAX_ARGS_CHARS or len(request.intent) > MAX_INTENT_CHARS:
            return failure_finding(on_error, "the call or the task is too large to review")
        key = (request, self.settings.mode, self.settings.model, self.settings.effort)
        result = self._cached(key)
        if result is None:
            try:
                result = self._ask(request)
            except FutureTimeout:
                log.error("keel-gate: the monitor timed out for tool %r", call.tool)
                return failure_finding(on_error, "timed out")
            except MonitorBusyError:
                log.error("keel-gate: the monitor is busy; tool %r gets the failure verdict", call.tool)
                return failure_finding(on_error, "the monitor is busy")
            except Exception as exc:  # noqa: BLE001 - any reviewer failure is a failed review (AC-214)
                log.error("keel-gate: the monitor failed for tool %r: %s", call.tool, type(exc).__name__)
                return failure_finding(on_error, "no valid answer")
            self._store(key, result)
        return monitor_finding(result)

    def _ask(self, request: ReviewRequest) -> ReviewResult:
        """Call the reviewer with a hard timeout and a bounded number of slots (AC-220).

        Anything but an exact ReviewResult is an error, and so is any exception the reviewer raises, even a
        BaseException such as SystemExit: decide() must never raise.
        """
        if self._reviewer is None or self._pool is None:
            raise RuntimeError("the monitor is not running")
        if not self._slots.acquire(blocking=False):
            raise MonitorBusyError
        try:
            future = self._pool.submit(self._reviewer.review, request)
        except BaseException:
            self._slots.release()
            raise
        future.add_done_callback(lambda _f: self._slots.release())
        try:
            result = future.result(timeout=self.settings.timeout_s)
        except FutureTimeout:
            future.cancel()  # drops it if it has not started; a running review keeps its slot until it ends
            raise
        except KeyboardInterrupt:
            raise
        except BaseException as exc:  # the reviewer's failure, even SystemExit, must become a failed review
            raise RuntimeError(f"the reviewer raised {type(exc).__name__}") from exc
        if type(result) is not ReviewResult:  # not isinstance: a subclass could skip validation (AC-222)
            raise TypeError("the reviewer did not return a ReviewResult")
        return result

    def _merge(self, decision: Decision, finding: Finding) -> Decision:
        if self.gate.settings.mode == "observe" and decision.verdict is Verdict.ALLOW:
            return _observe_monitor(decision, finding)
        merged = raise_only(decision, finding)
        if merged.verdict is decision.verdict:
            return merged
        # The monitor raised the answer: the agent gets a fixed message, never the monitor's own words.
        text = FAILED_MESSAGE if finding.rule_id == "monitor_error" else FLAGGED_MESSAGE
        return replace(merged, message_for_model=message_for(merged.verdict, text))

    def _cached(self, key: _CacheKey) -> ReviewResult | None:
        with self._lock:
            result = self._cache.get(key)
            if result is not None:
                self._cache.move_to_end(key)
            return result

    def _store(self, key: _CacheKey, result: ReviewResult) -> None:
        with self._lock:
            self._cache[key] = result
            self._cache.move_to_end(key)
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)


def _observe_monitor(decision: Decision, finding: Finding) -> Decision:
    """Observe mode: record what the monitor would add, but keep the call allowed (AC-215)."""
    before = decision.observed_verdict or Verdict.ALLOW
    observed = finding.verdict if finding.verdict.rank > before.rank else before
    would = "denied" if observed is Verdict.DENY else "asked"
    reasons = [r for r in decision.reasons if not r.startswith(_WOULD_HAVE)]
    reasons += [finding.reason, f"{_WOULD_HAVE}{would}"]
    return replace(
        decision,
        tier=max(decision.tier, finding.tier, key=lambda t: t.rank),
        reasons=tuple(dict.fromkeys(reasons)),
        rule_ids=tuple(dict.fromkeys((*decision.rule_ids, finding.rule_id))),
        observed_verdict=observed,
        message_for_model=message_for(Verdict.ALLOW, ""),
    )
