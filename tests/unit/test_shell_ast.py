"""AC-010 to AC-015: shell commands are parsed, not string-matched."""

from __future__ import annotations

import pytest

from keel_gate.domain.models import Tier, Verdict
from keel_gate.domain.shell_ast import parse_shell
from keel_gate.gate import Gate
from tests.factories import make_session, make_shell

# --------------------------------------------------------------------------- parser (unit)


@pytest.mark.parametrize(
    ("command", "programs"),
    [
        ("ls; rm -rf ~", ["ls", "rm"]),
        ("a && b || c | d", ["a", "b", "c", "d"]),
        ("ls\nrm -rf ~", ["ls", "rm"]),
        ("(cd x && rm -rf ~)", ["cd", "rm"]),
        ("ls &", ["ls"]),
    ],
)
def test_ac_010_compound_commands_are_split(command: str, programs: list[str]) -> None:
    parsed = parse_shell(command)

    assert [c.program for c in parsed.commands] == programs


@pytest.mark.parametrize(
    "command",
    [
        "bash -c 'rm -rf ~'",
        'sh -c "rm -rf ~"',
        "env FOO=1 rm -rf ~",
        "timeout 5 rm -rf ~",
        "nice -n 5 rm -rf ~",
        "nohup rm -rf ~",
        "sudo -u root rm -rf ~",
        "xargs rm -rf ~",
        "command rm -rf ~",
    ],
)
def test_ac_011_wrappers_are_unwrapped(command: str) -> None:
    parsed = parse_shell(command)

    assert "rm" in [c.program for c in parsed.commands]


@pytest.mark.parametrize(
    "command",
    [
        "/bin/rm -rf ~",
        "/proc/self/root/usr/bin/rm -rf ~",
        "./rm -rf ~",
        "RM -rf ~",
        '"r""m" -rf ~',
        "'rm' -rf ~",
        "\\rm -rf ~",
    ],
)
def test_ac_012_the_real_program_is_resolved(command: str) -> None:
    parsed = parse_shell(command)

    assert parsed.commands[0].program == "rm"


def test_ac_012_npx_behind_a_proc_path_is_still_seen_as_npx() -> None:
    parsed = parse_shell("/proc/self/root/usr/bin/npx some-tool")

    assert (parsed.commands[0].wrapped_by, parsed.commands[0].program) == (("npx",), "some-tool")


@pytest.mark.parametrize("command", ["echo $(whoami)", "echo `whoami`", "rm -rf $(echo ~)", "eval ls"])
def test_ac_013_substitution_and_eval_are_flagged(command: str) -> None:
    parsed = parse_shell(command)

    assert parsed.has_substitution


def test_ac_013_commands_inside_substitution_are_seen() -> None:
    parsed = parse_shell("echo $(rm -rf ~)")

    assert "rm" in [c.program for c in parsed.commands]


def test_ac_013_decode_then_run_payload_is_decoded() -> None:
    parsed = parse_shell("echo cm0gLXJmIH4= | base64 -d | sh")

    assert parsed.decoded_scripts == ("rm -rf ~",)


@pytest.mark.parametrize("command", ["ls 'unterminated", "if then fi fi", "echo $((", "cat <<"])
def test_ac_014_unparseable_text_is_marked(command: str) -> None:
    parsed = parse_shell(command)

    assert parsed.parse_error


def test_ac_014_a_variable_as_the_program_is_dynamic() -> None:
    parsed = parse_shell("$CMD -rf ~")

    assert parsed.commands[0].dynamic_program


# --------------------------------------------------------------------------- through the gate


def _decide(gate: Gate, command: str) -> tuple[Verdict, Tier, tuple[str, ...]]:
    decision = gate.decide(make_shell(command), make_session())
    return decision.verdict, decision.tier, decision.rule_ids


def test_ac_010_one_dangerous_part_makes_the_whole_command_deny(gate: Gate) -> None:
    verdict, tier, rules = _decide(gate, "ls; rm -rf ~")

    assert (verdict, tier) == (Verdict.DENY, Tier.T3)
    assert "rm_rf_dangerous" in rules


@pytest.mark.parametrize(
    "command",
    [
        "bash -c 'rm -rf ~'",
        "env FOO=1 rm -rf ~",
        "timeout 5 rm -rf ~",
        "sudo -u root rm -rf ~",
        "nohup rm -rf ~",
        "npx rimraf ~",
    ],
)
def test_ac_011_wrapped_dangerous_commands_are_denied(gate: Gate, command: str) -> None:
    verdict, _, rules = _decide(gate, command)

    assert verdict is Verdict.DENY
    assert "rm_rf_dangerous" in rules


@pytest.mark.parametrize(
    "command",
    ["/proc/self/root/usr/bin/rm -rf ~", '"r""m" -rf ~', "RM -rf ~", "\\rm -rf ~"],
)
def test_ac_012_hidden_rm_is_denied(gate: Gate, command: str) -> None:
    verdict, _, rules = _decide(gate, command)

    assert verdict is Verdict.DENY
    assert "rm_rf_dangerous" in rules


@pytest.mark.parametrize("command", ["echo $(whoami)", "echo `whoami`", "eval ls", "ls $(pwd)"])
def test_ac_013_substitution_is_at_least_ask(gate: Gate, command: str) -> None:
    verdict, _, rules = _decide(gate, command)

    assert verdict is Verdict.ASK
    assert "shell_substitution" in rules


def test_ac_013_decoded_catastrophic_payload_is_denied(gate: Gate) -> None:
    verdict, tier, rules = _decide(gate, "echo cm0gLXJmIH4= | base64 -d | sh")

    assert (verdict, tier) == (Verdict.DENY, Tier.T3)
    assert "decode_then_run" in rules


def test_ac_013_decode_then_run_is_never_allowed(gate: Gate) -> None:
    verdict, _, rules = _decide(gate, "echo bHM= | base64 --decode | bash")

    assert verdict is Verdict.ASK
    assert "decode_then_run" in rules


@pytest.mark.parametrize("command", ["ls 'unterminated", "if then fi fi", "rm${IFS}-rf${IFS}~", "$CMD -rf ~"])
def test_ac_014_unparseable_or_dynamic_is_never_allowed(gate: Gate, command: str) -> None:
    verdict, _, _ = _decide(gate, command)

    assert verdict in (Verdict.ASK, Verdict.DENY)


@pytest.mark.parametrize(
    "command",
    [
        "find . -name '*.log' -delete",
        "find . -exec rm {} ;",
        "find . -execdir cat {} +",
        "fd -x rm",
        "git -c core.sshCommand=evil fetch",
        "go test -exec 'bash -c id' ./...",
        "ls | xargs sh -c 'echo hi'",
    ],
)
def test_ac_015_argument_injection_flags_are_at_least_ask(gate: Gate, command: str) -> None:
    verdict, _, rules = _decide(gate, command)

    assert verdict in (Verdict.ASK, Verdict.DENY)
    assert "argument_injection" in rules
