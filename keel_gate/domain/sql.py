"""Conservative SQL classification using lexical tokens, never executing SQL."""

from __future__ import annotations

import re
from typing import Literal

SqlKind = Literal["read", "write", "destructive"]
_RANK: dict[SqlKind, int] = {"read": 0, "write": 1, "destructive": 2}
_KEYWORDS = frozenset(
    [
        "SELECT",
        "WITH",
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "TRUNCATE",
        "ALTER",
        "CREATE",
        "REPLACE",
        "MERGE",
        "GRANT",
        "REVOKE",
        "SHOW",
        "EXPLAIN",
        "DESCRIBE",
        "DESC",
        "PRAGMA",
        "VACUUM",
        "COPY",
        "BEGIN",
        "COMMIT",
        "ROLLBACK",
        "UPSERT",
        "VALUES",
        "ANALYZE",
        "REINDEX",
        "CLUSTER",
        "COMMENT",
        "LOCK",
        "CALL",
        "EXEC",
        "EXECUTE",
        "LOAD",
        "RENAME",
        "FLUSH",
    ]
)
_TOKEN = re.compile(
    r"--[^\n]*|/\*.*?\*/|'(?:''|\\.|[^'\\])*'|\"(?:\"\"|[^\"])*\"|"
    r"\$[A-Za-z_0-9]*\$.*?\$[A-Za-z_0-9]*\$|[A-Za-z_][A-Za-z_0-9]*|[0-9]+|[^\s]",
    re.DOTALL,
)


def _lexemes(text: str) -> list[str]:
    result = []
    for match in _TOKEN.finditer(text):
        lexeme = match.group()
        if lexeme.startswith(("--", "/*")):
            continue
        # Quoted contents cannot supply SQL keywords or statement separators.
        result.append("LITERAL" if lexeme.startswith(("'", '"', "$")) else lexeme.upper())
    return result


def looks_like_sql(text: str) -> bool:
    lexemes = _lexemes(text)
    lexemes = [part for part in lexemes if part != "("]
    return bool(lexemes) and lexemes[0] in _KEYWORDS


def _statement(lexemes: list[str]) -> SqlKind:
    if not lexemes:
        return "read"
    verb = lexemes[0]
    if verb in ("DROP", "TRUNCATE") or (verb == "ALTER" and "DROP" in lexemes):
        return "destructive"
    if verb in ("DELETE", "UPDATE"):
        # Only a WHERE in the outer statement constrains the affected rows.
        depth = 0
        for i, lexeme in enumerate(lexemes):
            if lexeme == "(":
                depth += 1
            elif lexeme == ")":
                depth -= 1
            elif lexeme == "WHERE" and depth == 0:
                condition = lexemes[i + 1 :]
                while condition[:1] == ["("] and condition[-1:] == [")"]:
                    condition = condition[1:-1]
                if condition[:1] == ["TRUE"] or condition in (["1"], ["1", "=", "1"]):
                    return "destructive"
                return "write"
        return "destructive"
    if verb == "WITH":
        kinds = [
            _statement(lexemes[i:])
            for i, lexeme in enumerate(lexemes)
            if lexeme in {"DELETE", "UPDATE", "INSERT", "DROP", "TRUNCATE", "MERGE"}
        ]
        return max(kinds, key=lambda k: _RANK[k]) if kinds else "read"
    if verb in {"SELECT", "SHOW", "EXPLAIN", "DESCRIBE", "DESC", "VALUES"}:
        return "write" if "INTO" in lexemes or (verb == "EXPLAIN" and "ANALYZE" in lexemes) else "read"
    return "write"


def classify_sql(text: str) -> SqlKind:
    """Return the most dangerous statement, ignoring keywords inside quoted data."""
    statements: list[list[str]] = [[]]
    for lexeme in _lexemes(text):
        if lexeme == ";":
            statements.append([])
        else:
            statements[-1].append(lexeme)
    return max((_statement(s) for s in statements), key=lambda k: _RANK[k])
