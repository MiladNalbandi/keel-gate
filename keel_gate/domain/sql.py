"""Classify SQL text as read, write, or destructive (AC-023).

Destructive means it cannot be undone and hits everything: DROP, TRUNCATE, ALTER … DROP, and DELETE or UPDATE without
a WHERE clause. Unknown statements count as writes, never as reads (fail closed).
"""

from __future__ import annotations

import re
from typing import Literal

SqlKind = Literal["read", "write", "destructive"]

_RANK: dict[SqlKind, int] = {"read": 0, "write": 1, "destructive": 2}
_KEYWORDS = (
    "select|with|insert|update|delete|drop|truncate|alter|create|replace|merge|grant|revoke|show|explain|describe|"
    "desc|pragma|vacuum|copy|begin|commit|rollback|upsert|values|analyze|reindex|cluster|comment|lock|call|exec|"
    "execute|load|rename|flush"
)
_LOOKS_LIKE_SQL = re.compile(rf"^\s*\(?\s*(?:{_KEYWORDS})\b", re.IGNORECASE)
_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_WHERE = re.compile(r"\bwhere\b", re.IGNORECASE)
_WRITE_IN_CTE = re.compile(r"\b(delete|update|insert|drop|truncate|merge)\b", re.IGNORECASE)
_READ = frozenset({"SELECT", "SHOW", "EXPLAIN", "DESCRIBE", "DESC", "VALUES"})


def looks_like_sql(text: str) -> bool:
    return bool(_LOOKS_LIKE_SQL.match(text))


def _statement(stmt: str) -> SqlKind:
    words = stmt.lstrip("( \t\n").split(None, 1)
    if not words:
        return "read"
    verb = words[0].upper()
    if verb in ("DROP", "TRUNCATE"):
        return "destructive"
    if verb in ("DELETE", "UPDATE"):
        return "write" if _WHERE.search(stmt) else "destructive"
    if verb == "ALTER":
        return "destructive" if re.search(r"\bdrop\b", stmt, re.IGNORECASE) else "write"
    if verb == "WITH":
        match = _WRITE_IN_CTE.search(stmt)
        return _statement(stmt[match.start() :]) if match else "read"
    if verb in _READ:
        return "write" if verb == "SELECT" and re.search(r"\binto\b", stmt, re.IGNORECASE) else "read"
    return "write"


def classify_sql(text: str) -> SqlKind:
    """The most dangerous kind among all statements in `text`."""
    clean = _BLOCK_COMMENT.sub(" ", _LINE_COMMENT.sub(" ", text))
    kinds = [_statement(s) for s in clean.split(";") if s.strip()]
    if not kinds:
        return "read"
    return max(kinds, key=lambda k: _RANK[k])
