"""AC-020 to AC-024: tiers and the built-in rules."""

from __future__ import annotations

import pytest

from keel_gate.domain.models import Tier, Verdict
from keel_gate.gate import Gate
from tests.factories import make_call, make_session, make_shell


def _shell(gate: Gate, command: str):  # type: ignore[no-untyped-def]
    return gate.decide(make_shell(command), make_session())


@pytest.mark.parametrize(
    "command",
    [
        "ls -la",
        "cat README.md",
        "grep -rn TODO src",
        "git status",
        "git log --oneline -5",
        "git diff HEAD~1",
        "head -n 20 src/cart.py | wc -l",
    ],
)
def test_ac_020_read_only_commands_are_allowed_t0(gate: Gate, command: str) -> None:
    decision = _shell(gate, command)

    assert (decision.verdict, decision.tier) == (Verdict.ALLOW, Tier.T0)


def test_ac_020_read_only_tool_is_allowed_t0(gate: Gate) -> None:
    decision = gate.decide(make_call("read_file", {"path": "src/cart.py"}), make_session())

    assert (decision.verdict, decision.tier) == (Verdict.ALLOW, Tier.T0)


def test_ac_020_reversible_tool_is_allowed_t1(gate: Gate) -> None:
    call = make_call("edit_file", {"path": "src/cart.py", "old_string": "a", "new_string": "b"})

    decision = gate.decide(call, make_session())

    assert (decision.verdict, decision.tier) == (Verdict.ALLOW, Tier.T1)


def test_ac_020_irreversible_tool_asks_t2(gate: Gate) -> None:
    decision = gate.decide(make_call("payments.refund", {"order": "1042", "amount": "500.00"}), make_session())

    assert (decision.verdict, decision.tier) == (Verdict.ASK, Tier.T2)


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "rm -rf ~",
        "rm -rf ~/Documents",
        "rm -rf $HOME",
        "rm -rf /etc",
        "rm -fr /var/lib/postgres",
        "rm --recursive --force ../other-project",
        'rm -rf "$EMPTY/"',
        'rm -rf "${BUILD_DIR}/"',
        "rm -rf /work/shop/../",
    ],
)
def test_ac_021_dangerous_recursive_delete_is_denied_t3(gate: Gate, command: str) -> None:
    decision = _shell(gate, command)

    assert (decision.verdict, decision.tier) == (Verdict.DENY, Tier.T3)
    assert "rm_rf_dangerous" in decision.rule_ids


def test_ac_021_recursive_delete_inside_the_workspace_asks(gate: Gate) -> None:
    decision = _shell(gate, "rm -rf build/tmp")

    assert (decision.verdict, decision.tier) == (Verdict.ASK, Tier.T2)


def test_ac_021_windows_drive_wipe_is_denied(gate: Gate) -> None:
    decision = _shell(gate, "rmdir /s /q D:\\")

    assert decision.verdict is Verdict.DENY


@pytest.mark.parametrize(
    "command",
    [
        "git push --force origin main",
        "git push -f origin main",
        "git push --force-with-lease origin master",
        "git push origin +main",
        "git push origin +HEAD:release/2.0",
        "git push --force",
    ],
)
def test_ac_022_force_push_to_protected_branch_is_denied(gate: Gate, command: str) -> None:
    decision = _shell(gate, command)

    assert (decision.verdict, decision.tier) == (Verdict.DENY, Tier.T3)
    assert "git_force_protected" in decision.rule_ids


@pytest.mark.parametrize("command", ["git push origin feature/cart", "git push --force origin feature/cart"])
def test_ac_022_other_pushes_ask(gate: Gate, command: str) -> None:
    decision = _shell(gate, command)

    assert decision.verdict is Verdict.ASK


@pytest.mark.parametrize(
    "command",
    [
        "psql $PROD_URL -c 'DROP TABLE users;'",
        'mysql -e "truncate table logs"',
        'sqlite3 shop.db "DELETE FROM users"',
        'psql -c "update users set admin = true"',
        "psql -c 'drop database shop'",
    ],
)
def test_ac_023_destructive_sql_through_a_client_is_denied(gate: Gate, command: str) -> None:
    decision = _shell(gate, command)

    assert (decision.verdict, decision.tier) == (Verdict.DENY, Tier.T3)
    assert "sql_drop" in decision.rule_ids


def test_ac_023_sql_with_where_is_not_denied(gate: Gate) -> None:
    decision = _shell(gate, "psql -c 'DELETE FROM users WHERE id = 1'")

    assert decision.verdict is Verdict.ASK


@pytest.mark.parametrize(
    "query",
    ["DROP TABLE customers", "truncate orders", "delete from users", "UPDATE users SET admin = 1"],
)
def test_ac_023_destructive_sql_through_a_tool_is_denied(gate: Gate, query: str) -> None:
    decision = gate.decide(make_call("sql.query", {"query": query}), make_session())

    assert (decision.verdict, decision.tier) == (Verdict.DENY, Tier.T3)
    assert "sql_drop" in decision.rule_ids


def test_ac_023_select_through_a_tool_is_allowed(gate: Gate) -> None:
    decision = gate.decide(make_call("sql.query", {"query": "SELECT id FROM users LIMIT 5"}), make_session())

    assert (decision.verdict, decision.tier) == (Verdict.ALLOW, Tier.T0)


def test_ac_024_destructive_remote_tool_is_denied(gate: Gate) -> None:
    decision = gate.decide(make_call("infra.volume_delete", {"volume_id": "vol_1"}), make_session())

    assert (decision.verdict, decision.tier) == (Verdict.DENY, Tier.T3)
    assert "remote_destructive" in decision.rule_ids


@pytest.mark.parametrize(
    "command",
    [
        "curl -X DELETE https://api.example-cloud.com/v1/volumes/vol_1",
        "curl --request DELETE https://api.example-cloud.com/v1/projects/p1",
        "curl -X POST https://backboard.railway.app/graphql/v2 -H 'Authorization: Bearer x' "
        '-d \'{"query":"mutation { volumeDelete(volumeId: \\"v1\\") }"}\'',
    ],
)
def test_ac_024_destructive_http_calls_are_denied(gate: Gate, command: str) -> None:
    decision = _shell(gate, command)

    assert (decision.verdict, decision.tier) == (Verdict.DENY, Tier.T3)
    assert "remote_destructive" in decision.rule_ids
