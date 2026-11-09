"""AC-023: SQL is classified as read, write, or destructive. Unknown statements are writes, never reads."""

from __future__ import annotations

import pytest

from keel_gate.domain.sql import classify_sql, looks_like_sql


@pytest.mark.parametrize(("text", "expected"), [("SELECT 1", True), ("  (select 1)", True), ("shop.db", False)])
def test_ac_023_only_sql_looking_text_is_checked(text: str, expected: bool) -> None:
    assert looks_like_sql(text) is expected


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("", "read"),
        ("-- only a comment", "read"),
        ("/* drop table x */ SELECT 1", "read"),
        ("SHOW TABLES", "read"),
        ("WITH a AS (SELECT 1) SELECT * FROM a", "read"),
        ("SELECT * INTO backup FROM users", "write"),
        ("ALTER TABLE t ADD COLUMN c int", "write"),
        ("VACUUM", "write"),
        ("DELETE FROM users WHERE id = 1", "write"),
        ("WITH a AS (SELECT 1) DELETE FROM t", "destructive"),
        ("ALTER TABLE t DROP COLUMN c", "destructive"),
        ("INSERT INTO t VALUES (1); DROP TABLE t", "destructive"),
        ("DELETE FROM users -- WHERE id = 1", "destructive"),
    ],
)
def test_ac_023_statements_are_classified(text: str, kind: str) -> None:
    assert classify_sql(text) == kind
