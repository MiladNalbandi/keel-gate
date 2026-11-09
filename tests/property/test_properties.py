"""Property tests: generated inputs for AC-007 and AC-010 to AC-014."""

from __future__ import annotations

from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from keel_gate.domain.canonical import call_hash
from keel_gate.domain.manifest import Manifest
from keel_gate.domain.models import Verdict
from keel_gate.gate import Gate
from tests.factories import TEST_TOOLS, make_session, make_shell

_GATE = Gate(Manifest.from_mapping(TEST_TOOLS))

json_scalars = st.none() | st.booleans() | st.integers(-(10**6), 10**6) | st.text(max_size=20)
json_values = st.recursive(
    json_scalars,
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=8), inner, max_size=4),
    max_leaves=12,
)
json_args = st.dictionaries(st.text(min_size=1, max_size=8), json_values, min_size=1, max_size=6)


@given(args=json_args)
def test_ac_007_key_order_never_changes_the_hash(args: dict[str, Any]) -> None:
    reordered = dict(reversed(list(args.items())))

    assert call_hash("t", args) == call_hash("t", reordered)


@given(args=json_args, key=st.text(min_size=1, max_size=8), value=json_values)
def test_ac_007_any_change_changes_the_hash(args: dict[str, Any], key: str, value: Any) -> None:
    changed = {**args, key: value}
    fresh_key = key
    while changed == args:
        fresh_key += "_x"
        changed = {**args, fresh_key: value}

    assert call_hash("t", args) != call_hash("t", changed)


# --------------------------------------------------------------- obfuscated catastrophic commands

programs = st.sampled_from(
    ["rm", "/bin/rm", "/usr/bin/rm", "/proc/self/root/usr/bin/rm", '"r""m"', "'rm'", "\\rm", "RM"]
)
flags = st.sampled_from(["-rf", "-fr", "-r -f", "-Rf", "--recursive --force", "-r"])
targets = st.sampled_from(["~", "/", "$HOME", "~/", '"$EMPTY/"', "/etc", "../../"])
wrappers = st.sampled_from(["", "sudo ", "env A=1 ", "timeout 9 ", "nice -n 1 ", "nohup ", "command "])
joiners = st.sampled_from(["{cmd}", "ls; {cmd}", "true && {cmd}", "false || {cmd}", "({cmd})", "bash -c '{cmd}'"])


@settings(max_examples=300)
@given(program=programs, flag=flags, target=targets, wrapper=wrappers, joiner=joiners)
def test_ac_010_to_014_obfuscated_recursive_delete_is_never_allowed(
    program: str, flag: str, target: str, wrapper: str, joiner: str
) -> None:
    inner = f"{wrapper}{program} {flag} {target}"
    if "bash -c" in joiner:
        inner = inner.replace("'", "")
    command = joiner.format(cmd=inner)

    decision = _GATE.decide(make_shell(command), make_session())

    assert decision.verdict is Verdict.DENY, command
