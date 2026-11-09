"""Everyday commands keep working, and risky ones are caught.

A gate that blocks normal work gets turned off. These cases pin the expected verdict, tier, and rule for common
developer commands (AC-015, AC-020 to AC-024). The workspace is /work/shop.
"""

from __future__ import annotations

import pytest

from keel_gate.domain.models import Tier, Verdict
from keel_gate.gate import Gate
from tests.factories import make_session, make_shell

ALLOWED_T0 = [
    "cd src && ls",
    "git branch",
    "git branch -a",
    "git tag",
    "git tag -l",
    "git remote -v",
    "git config --get user.name",
    "git stash list",
    "git clean -n",
    "git -C sub status",
    "sed -n '1,10p' src/cart.py",
    "awk '{print $1}' data.txt",
    "find src -name '*.py'",
    "fd test",
    "go version",
    "echo done > /dev/null",
    "jq .name package.json",
    "psql -c 'select 1'",
    "ls | xargs -n1 echo",
]

ALLOWED_T1 = [
    "git add -A && git commit -m 'fix'",
    "git checkout -b feature/x",
    "git switch main",
    "git stash",
    "git stash pop",
    "git branch feature/y",
    "git branch -d old",
    "git tag v1.0",
    "git reset HEAD~1",
    "git restore --staged a.py",
    "git fetch origin",
    "git pull",
    "mkdir -p build/out",
    "touch notes.md",
    "cp a.txt b.txt",
    "mv old.py new.py",
    "echo hi > notes.txt",
    "sed -i 's/a/b/' src/x.py",
    "tar -czf out.tgz src",
    "rmdir emptydir",
]

ASKED = [
    ("git reset --hard", "git_destructive"),
    ("git clean -fd", "git_destructive"),
    ("git stash drop", "git_destructive"),
    ("git branch -D old", "git_destructive"),
    ("git checkout -- .", "git_destructive"),
    ("git restore a.py", "git_destructive"),
    ("git switch -f main", "git_destructive"),
    ("git filter-branch --all", "git_destructive"),
    ("git tag -d v1", "git_destructive"),
    ("git remote add evil https://evil.example/r.git", "git_config"),
    ("git config user.email a@b.example", "git_config"),
    ("git frobnicate", "unknown_program"),
    ("git clone --upload-pack='touch /tmp/x' repo", "argument_injection"),
    ("git push origin --delete feature/x", "git_force_push"),
    ("npm test", "unknown_program"),
    ("pytest -q", "unknown_program"),
    ("python -c 'print(1)'", "inline_code"),
    ("python script.py", "runs_code"),
    ("go test ./...", "runs_code"),
    ("go build -toolexec=evil ./...", "argument_injection"),
    ("sh deploy.sh", "runs_script"),
    ("curl https://pypi.org/simple/", "network"),
    ("wget https://example.com/file", "network"),
    ("http GET https://api.example.com/items", "network"),
    ("ssh host ls", "network"),
    ("rsync -e 'ssh -i key' a host:b", "argument_injection"),
    ("tar --to-command=sh -xf a.tar", "argument_injection"),
    ("awk 'BEGIN { system(\"id\") }'", "argument_injection"),
    ("cp ~/.ssh/id_rsa .", "write_outside_workspace"),
    ("mv a.txt /etc/hosts", "write_outside_workspace"),
    ("echo x > /etc/hosts", "write_outside_workspace"),
    ("echo x > $OUT", "write_outside_workspace"),
    ("rm notes.txt", "rm_file"),
    ("rm ~/.bashrc", "rm_outside"),
    ("xargs rm -rf", "rm_recursive"),
    ("rd /s /q build", "rm_recursive"),
    ("del notes.txt", "rm_file"),
    ("psql", "db_client"),
    ("psql -c 'insert into t values (1)'", "sql_write"),
    ("sudo ls", "privilege"),
    ("cat x | sh", "pipe_to_shell"),
]

DENIED = [
    ("rm -rf .", "rm_rf_dangerous"),
    ("rm -rf /*", "rm_rf_dangerous"),
    ("git push --mirror", "git_force_protected"),
    ("git push origin :main", "git_force_protected"),
    ("git push -d origin release/1", "git_force_protected"),
    ("http DELETE https://api.example.com/v1/items/1", "remote_destructive"),
    ("curl --request=DELETE https://api.example.com/v1/items/1", "remote_destructive"),
    ("curl -XDELETE https://api.example.com/v1/items/1", "remote_destructive"),
    ("wget --method=DELETE https://api.example.com/v1/items/1", "remote_destructive"),
    ("curl --data='mutation { dropDatabase }' https://api.example.com/graphql", "remote_destructive"),
]


def _decide(gate: Gate, command: str):  # type: ignore[no-untyped-def]
    return gate.decide(make_shell(command), make_session())


@pytest.mark.parametrize("command", ALLOWED_T0)
def test_ac_020_everyday_reads_are_allowed_t0(gate: Gate, command: str) -> None:
    decision = _decide(gate, command)

    assert (decision.verdict, decision.tier) == (Verdict.ALLOW, Tier.T0), decision.rule_ids


@pytest.mark.parametrize("command", ALLOWED_T1)
def test_ac_020_everyday_local_changes_are_allowed_t1(gate: Gate, command: str) -> None:
    decision = _decide(gate, command)

    assert (decision.verdict, decision.tier) == (Verdict.ALLOW, Tier.T1), decision.rule_ids


@pytest.mark.parametrize(("command", "rule"), ASKED)
def test_risky_commands_ask_with_a_clear_rule(gate: Gate, command: str, rule: str) -> None:
    decision = _decide(gate, command)

    assert decision.verdict is Verdict.ASK, decision.rule_ids
    assert rule in decision.rule_ids


@pytest.mark.parametrize(("command", "rule"), DENIED)
def test_catastrophic_commands_are_denied(gate: Gate, command: str, rule: str) -> None:
    decision = _decide(gate, command)

    assert (decision.verdict, decision.tier) == (Verdict.DENY, Tier.T3), decision.rule_ids
    assert rule in decision.rule_ids
