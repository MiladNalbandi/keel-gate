"""Test data builders. Each test builds only the data it cares about; defaults fill the rest."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from keel_gate.domain.models import Session, ToolCall

WORKSPACE = "/work/shop"

_STRING = {"type": "string", "minLength": 1, "maxLength": 10000}

TEST_TOOLS: dict[str, dict[str, Any]] = {
    "shell": {
        "kind": "shell",
        "description": "Run a shell command in the workspace.",
        "read_only": False,
        "state_changing": True,
        "reversible": False,
        "schema": {
            "type": "object",
            "required": ["command"],
            "properties": {"command": _STRING},
            "additionalProperties": False,
        },
    },
    "read_file": {
        "description": "Read a text file.",
        "read_only": True,
        "state_changing": False,
        "reversible": True,
        "schema": {
            "type": "object",
            "required": ["path"],
            "properties": {"path": _STRING},
            "additionalProperties": False,
        },
    },
    "edit_file": {
        "description": "Replace text in a file.",
        "read_only": False,
        "state_changing": True,
        "reversible": True,
        "schema": {
            "type": "object",
            "required": ["path", "old_string", "new_string"],
            "properties": {
                "path": _STRING,
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "payments.refund": {
        "description": "Refund an order.",
        "read_only": False,
        "state_changing": True,
        "reversible": False,
        "remote": True,
        "mandate_ok": True,
        "schema": {
            "type": "object",
            "required": ["order", "amount"],
            "properties": {
                "order": {"type": "string", "pattern": "^[0-9]{1,10}$"},
                "amount": {"type": "string", "pattern": "^[0-9]+\\.[0-9]{2}$"},
                "currency": {"type": "string", "enum": ["USD", "EUR"]},
            },
            "additionalProperties": False,
        },
    },
    "infra.volume_delete": {
        "description": "Delete a cloud volume.",
        "read_only": False,
        "state_changing": True,
        "reversible": False,
        "remote": True,
        "destructive": True,
        "schema": {
            "type": "object",
            "required": ["volume_id"],
            "properties": {"volume_id": _STRING},
            "additionalProperties": False,
        },
    },
    "sql.query": {
        "description": "Run one SQL statement.",
        "read_only": False,
        "state_changing": True,
        "reversible": False,
        "sql_arg": "query",
        "schema": {
            "type": "object",
            "required": ["query"],
            "properties": {"query": _STRING},
            "additionalProperties": False,
        },
    },
    "web.fetch": {
        "description": "Fetch a web page.",
        "read_only": True,
        "state_changing": False,
        "reversible": True,
        "egress": True,
        "result_label": "untrusted",
        "schema": {
            "type": "object",
            "required": ["url"],
            "properties": {"url": _STRING},
            "additionalProperties": False,
        },
    },
}


def make_call(tool: str = "read_file", args: Mapping[str, Any] | None = None) -> ToolCall:
    return ToolCall(tool=tool, args=dict(args if args is not None else {"path": "README.md"}))


def make_shell(command: str) -> ToolCall:
    return ToolCall(tool="shell", args={"command": command})


def make_session(**overrides: Any) -> Session:
    values: dict[str, Any] = {
        "session_id": "s_test_01",
        "agent_id": "test-agent",
        "workspace": WORKSPACE,
    }
    values.update(overrides)
    return Session(**values)


class FakeClock:
    """A wall clock for tests: it only moves when the test moves it."""

    def __init__(self, start: str = "2026-11-09T10:00:00+00:00") -> None:
        from datetime import datetime

        self.now = datetime.fromisoformat(start)

    def __call__(self):  # type: ignore[no-untyped-def]
        return self.now

    def advance(self, **delta: float) -> None:
        from datetime import timedelta

        self.now = self.now + timedelta(**delta)


# ---------- monitor (Amendment A3) ----------

TASK = "Fix the failing test in tests/test_cart.py."


class ScriptedReviewer:
    """A Reviewer for tests. Each answer is a ReviewResult, an exception to raise, or a callable(request)."""

    def __init__(self, *answers: Any, delay_s: float = 0.0) -> None:
        self.answers = list(answers) or [_fits()]
        self.delay_s = delay_s
        self.requests: list[Any] = []

    def review(self, request: Any) -> Any:
        import time

        self.requests.append(request)
        if self.delay_s:
            time.sleep(self.delay_s)
        answer = self.answers[min(len(self.requests), len(self.answers)) - 1]
        if isinstance(answer, BaseException):
            raise answer
        if callable(answer):
            return answer(request)
        return answer


def _fits() -> Any:
    from keel_gate.domain.review import ReviewResult

    return ReviewResult("fits", "the call serves the task")


def verdict(kind: str, reason: str = "scripted answer") -> Any:
    from keel_gate.domain.review import ReviewResult

    return ReviewResult(kind, reason)  # type: ignore[arg-type]


def text_block(text: str) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(type="text", text=text)


def model_answer(kind: str = "fits", reason: str = "ok", **extra: Any) -> Any:
    """A fake Messages API response whose only block is the monitor's JSON answer."""
    import json

    return model_response(text_block(json.dumps({"verdict": kind, "reason": reason, **extra})))


def model_response(*content: Any, stop_reason: str = "end_turn", **fields: Any) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(stop_reason=stop_reason, content=list(content), **fields)


class FakeAnthropic:
    """Stands in for anthropic.Anthropic: records every request, returns scripted responses, never uses the network."""

    def __init__(self, *responses: Any, delay_s: float = 0.0) -> None:
        from types import SimpleNamespace

        self.responses = list(responses) or [model_answer()]
        self.delay_s = delay_s
        self.requests: list[dict[str, Any]] = []
        self.options: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(create=self._create)

    def with_options(self, **options: Any) -> FakeAnthropic:
        self.options.append(options)
        return self

    def _create(self, **request: Any) -> Any:
        import time

        self.requests.append(request)
        if self.delay_s:
            time.sleep(self.delay_s)
        response = self.responses[min(len(self.requests), len(self.responses)) - 1]
        if isinstance(response, BaseException):
            raise response
        return response
