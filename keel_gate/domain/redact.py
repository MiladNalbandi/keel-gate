"""Replace secret-looking values before data leaves the gate (AC-217; reused by the audit log, AC-131).

Pattern-based, so it catches common secret shapes, not every secret. It is a second line: secrets should not be in
tool arguments in the first place (the vault keeps them out, AC-100).
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Mapping
from typing import Any

REDACTED = "[redacted]"

# Secret-looking names inside free text (name=value, --flag value). "auth" is left out here on purpose:
# "--author=alice" is common and harmless. Mapping keys use the stricter word-part check in _secret_key().
_NAME = r"(?:password|passwd|passphrase|pwd|secret|token|api[_-]?key|private[_-]?key|access[_-]?key|credential)"
_NOT_DONE = r"(?!\[redacted\])"

# (pattern, replacement). Order matters: whole blocks and headers first, then token shapes, then name=value pairs.
_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
        REDACTED,
    ),
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^/\s:@]*:)[^@\s/]+@"), rf"\1{REDACTED}@"),
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/-]{12,}=*"), rf"\1{REDACTED}"),
    (re.compile(r"(?i)\b(authorization:\s*basic\s+)\S+"), rf"\1{REDACTED}"),
    (re.compile(r"(?i)\b((?:set-)?cookie:\s*)[^\n]+"), rf"\1{REDACTED}"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), REDACTED),
    (re.compile(r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{10,}"), REDACTED),
    (re.compile(r"\bwhsec_[A-Za-z0-9]{16,}"), REDACTED),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), REDACTED),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), REDACTED),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), REDACTED),
    (re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"), REDACTED),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}"), REDACTED),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), REDACTED),
    # --password hunter2, --api-key=abc
    (
        re.compile(
            rf"(?i)(?<![\w-])(--?[A-Za-z0-9-]*{_NAME.replace('[_-]', '-?')}[A-Za-z0-9-]*(?:=|\s+)){_NOT_DONE}\S+"
        ),
        rf"\1{REDACTED}",
    ),
    # aws configure set aws_secret_access_key VALUE (a name and its value with only a space between)
    (re.compile(rf"(?i)(\baws\s+configure\s+set\s+\S*(?:secret|token|key)\S*\s+){_NOT_DONE}\S+"), rf"\1{REDACTED}"),
    # mysql -phunter2 (the password is glued to -p)
    (
        re.compile(rf"(?i)(\b(?:mysql|mysqldump|mysqladmin|mariadb)\b[^\n|;&]*?\s-p){_NOT_DONE}(?=\S)\S+"),
        rf"\1{REDACTED}",
    ),
    # password=x, API_KEY: x, "password": "x", PASSWORD="a b c"
    (
        re.compile(
            rf"""(?i)(["']?\b[A-Za-z0-9_]*{_NAME}[A-Za-z0-9_]*["']?\s*[=:]\s*){_NOT_DONE}("[^"\n]*"|'[^'\n]*'|[^\s,;}}'"]+)"""
        ),
        rf"\1{REDACTED}",
    ),
)

_SECRET_PARTS = frozenset(
    {
        "password",
        "passwd",
        "passphrase",
        "pwd",
        "pass",
        "secret",
        "token",
        "credential",
        "credentials",
        "cookie",
        "authorization",
        "auth",
        "apikey",
    }
)
_SECRET_PAIRS = frozenset(
    {
        ("api", "key"),
        ("private", "key"),
        ("access", "key"),
        ("secret", "key"),
        ("session", "id"),
        ("session", "key"),
        ("session", "token"),
    }
)
_CAMEL = re.compile(r"([a-z0-9])([A-Z])")
_PARTS = re.compile(r"[^A-Za-z0-9]+")


def _secret_key(key: str) -> bool:
    """A mapping key names a secret when one of its word parts does (DB_PASS, apiKey), not on any substring."""
    parts = [p for p in _PARTS.split(_CAMEL.sub(r"\1_\2", key).lower()) if p]
    if parts == ["session"]:
        return True
    return any(p in _SECRET_PARTS for p in parts) or any(pair in _SECRET_PAIRS for pair in itertools.pairwise(parts))


def redact_text(text: str) -> str:
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return text


def redact_value(value: Any) -> Any:
    """A redacted copy of JSON-like data. Values under secret-looking keys are replaced whatever their type."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        out: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str):
                out[redact_text(key)] = REDACTED if _secret_key(key) else redact_value(item)
            else:
                out[key] = redact_value(item)
        return out
    if isinstance(value, list | tuple):
        return [redact_value(item) for item in value]
    return value
