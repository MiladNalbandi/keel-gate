"""Parse shell commands into the simple commands that will really run (AC-010 to AC-015).

String matching is not a security boundary: attackers hide commands with quotes, wrappers, absolute paths, encoding,
and substitution. This module parses the text with tree-sitter-bash into a syntax tree and returns every simple
command it finds, after:

- splitting lists, pipelines, subshells, and control structures (AC-010)
- unwrapping `sh -c`, `env`, `sudo`, `timeout`, `nice`, `nohup`, `xargs`, `npx` and similar wrappers (AC-011)
- resolving the program name: quotes, backslashes, paths, and case are removed (AC-012)
- noting substitution, eval, and "decode then run" pipelines, and decoding simple base64 payloads (AC-013)
- noting text that does not parse (AC-014)

It only parses. It does no I/O, and it does not decide anything; classify.py does.
"""

from __future__ import annotations

import base64
import binascii
import posixpath
import re
import threading
from dataclasses import dataclass, replace
from functools import lru_cache
from itertools import pairwise

import tree_sitter_bash
from tree_sitter import Language, Node, Parser

_LANGUAGE = Language(tree_sitter_bash.language())
_LOCAL = threading.local()

MAX_DEPTH = 4
MAX_UNWRAP = 8

SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "fish", "ash", "csh", "tcsh"})
DYNAMIC_NODES = frozenset(
    {
        "simple_expansion",
        "expansion",
        "command_substitution",
        "arithmetic_expansion",
        "process_substitution",
    }
)
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


@dataclass(frozen=True, slots=True)
class Word:
    """One shell word: its source text and its literal value (None when it depends on run-time expansion)."""

    raw: str
    value: str | None


@dataclass(frozen=True, slots=True)
class Redirect:
    op: str
    target: Word


@dataclass(frozen=True, slots=True)
class SimpleCommand:
    program: str
    args: tuple[Word, ...]
    text: str
    cwd: str | None = ""
    stdin: tuple[Word, ...] = ()
    local_program: bool = False
    dynamic_program: bool = False
    wrapped_by: tuple[str, ...] = ()
    redirects: tuple[Redirect, ...] = ()
    in_substitution: bool = False

    @property
    def values(self) -> tuple[str | None, ...]:
        return tuple(w.value for w in self.args)


@dataclass(frozen=True, slots=True)
class ShellParse:
    source: str
    commands: tuple[SimpleCommand, ...]
    parse_error: bool = False
    has_substitution: bool = False
    decode_then_run: bool = False
    pipe_to_shell: bool = False
    shell_eval: bool = False
    env_hijack: bool = False
    opaque_script: bool = False
    decoded_scripts: tuple[str, ...] = ()


def _parser() -> Parser:
    parser: Parser | None = getattr(_LOCAL, "parser", None)
    if parser is None:
        parser = Parser(_LANGUAGE)
        _LOCAL.parser = parser
    return parser


def program_name(value: str) -> str:
    """'/proc/self/root/usr/bin/RM' -> 'rm'. Case is folded because case-insensitive file systems run 'RM' as rm."""
    return value.strip().replace("\\", "/").rsplit("/", 1)[-1].lower()


def _unescape(text: str) -> str:
    return re.sub(r"\\(.)", r"\1", text, flags=re.DOTALL)


@lru_cache(maxsize=4096)
def parse_shell(command: str) -> ShellParse:
    """Parse a command line. Results are cached because agents repeat commands often."""
    return _Walker(command, depth=0).run()


class _Walker:
    def __init__(self, source: str, depth: int) -> None:
        self.source = source
        self.src = source.encode("utf-8")
        self.depth = depth
        self.commands: list[SimpleCommand] = []
        self.cwd: str | None = ""
        self.parse_error = False
        self.has_substitution = False
        self.decode_then_run = False
        self.pipe_to_shell = False
        self.shell_eval = False
        self.env_hijack = False
        self.opaque_script = False
        self.decoded: list[str] = []

    # ------------------------------------------------------------------ driver

    def run(self) -> ShellParse:
        tree = _parser().parse(self.src)
        self.parse_error = tree.root_node.has_error
        self._visit(tree.root_node, in_sub=False)
        return ShellParse(
            source=self.source,
            commands=tuple(self.commands),
            parse_error=self.parse_error,
            has_substitution=self.has_substitution,
            decode_then_run=self.decode_then_run,
            pipe_to_shell=self.pipe_to_shell,
            shell_eval=self.shell_eval,
            env_hijack=self.env_hijack,
            opaque_script=self.opaque_script,
            decoded_scripts=tuple(self.decoded),
        )

    def _text(self, node: Node) -> str:
        return self.src[node.start_byte : node.end_byte].decode("utf-8", "replace")

    # ------------------------------------------------------------------ tree walk

    def _visit(self, node: Node, in_sub: bool) -> None:
        kind = node.type
        self._note_eval(node)
        if kind == "variable_assignment":
            name = node.child_by_field_name("name")
            if name is not None and _hijacks_environment(self._text(name)):
                self.env_hijack = True
        if kind in ("command_substitution", "process_substitution"):
            self.has_substitution = True
            previous = self.cwd
            for child in node.named_children:
                self._visit(child, in_sub=True)
            self.cwd = previous
        elif kind == "command":
            self._command(node, in_sub)
        elif kind == "redirected_statement":
            self._redirected(node, in_sub)
        elif kind == "subshell":
            previous = self.cwd
            for child in node.named_children:
                self._visit(child, in_sub)
            self.cwd = previous
        elif kind == "pipeline":
            self._pipeline(node, in_sub)
        else:
            for child in node.named_children:
                self._visit(child, in_sub)

    def _redirected(self, node: Node, in_sub: bool) -> None:
        redirects: list[Redirect] = []
        start = len(self.commands)
        for child in node.named_children:
            if child.type == "file_redirect":
                redirects.append(self._redirect(child))
                self._scan_substitutions(child, in_sub)
            elif child.type in ("heredoc_redirect", "herestring_redirect"):
                redirects.append(self._input_redirect(child))
                self._scan_substitutions(child, in_sub)
            else:
                self._visit(child, in_sub)
        if redirects:
            for i in range(start, len(self.commands)):
                cmd = self.commands[i]
                if not cmd.in_substitution or in_sub:
                    self.commands[i] = replace(cmd, redirects=cmd.redirects + tuple(redirects))

    def _input_redirect(self, node: Node) -> Redirect:
        if node.type == "herestring_redirect":
            target = self._word(node.named_children[-1])
        else:
            body = next((c for c in node.named_children if c.type == "heredoc_body"), None)
            target = Word(self._text(body), self._text(body)) if body is not None else Word("", None)
        return Redirect("<<<", target)

    def _redirect(self, node: Node) -> Redirect:
        op = next((c.type for c in node.children if not c.is_named), ">")
        target_node = node.child_by_field_name("destination") or (
            node.named_children[-1] if node.named_children else None
        )
        target = self._word(target_node) if target_node is not None else Word("", None)
        return Redirect(op=op, target=target)

    def _pipeline(self, node: Node, in_sub: bool) -> None:
        stages: list[SimpleCommand] = []
        for child in node.named_children:
            start = len(self.commands)
            self._visit(child, in_sub)
            added = [c for c in self.commands[start:] if c.in_substitution == in_sub]
            if added:
                stages.append(added[0])
        # Propagate only literal producer data, never execute it.
        for producer, consumer in pairwise(stages):
            payload = _echo_payload(producer)
            if payload is None:
                continue
            for i, command in enumerate(self.commands):
                if command is consumer:
                    if "xargs" in command.wrapped_by:
                        words = tuple(Word(v, v) for v in payload.split())
                        self.commands[i] = replace(command, args=(*command.args, *words))
                    else:
                        self.commands[i] = replace(command, stdin=(*command.stdin, Word(payload, payload)))
        self._check_pipeline(stages)

    def _scan_substitutions(self, node: Node, in_sub: bool) -> None:
        """Find command substitutions inside words, assignments, and redirects."""
        self._note_eval(node)
        for child in node.named_children:
            if child.type in ("command_substitution", "process_substitution"):
                self._visit(child, in_sub)
            else:
                self._scan_substitutions(child, in_sub)

    def _note_eval(self, node: Node) -> None:
        kind, text = node.type, self._text(node)
        if (
            kind in ("arithmetic_expansion", "subscript")
            or (kind == "compound_statement" and text.startswith("(("))
            or (kind == "test_command" and re.search(r"\s-(?:eq|ne|lt|le|gt|ge|v)\s", text))
            or (kind == "expansion" and re.search(r"^\$\{!|@P|:[^+?=\-]", text))
            or (kind == "declaration_command" and re.search(r"\s-[a-zA-Z]*[in]", text))
        ):
            self.shell_eval = True

    # ------------------------------------------------------------------ words

    def _literal(self, node: Node) -> str | None:
        kind = node.type
        text = self._text(node)
        if kind == "word":
            return _unescape(text)
        if kind == "ansi_c_string":
            return _ansi_literal(text[2:-1])
        if kind == "raw_string":
            return text[1:-1]
        if kind == "string":
            if any(c.type in DYNAMIC_NODES for c in node.named_children):
                return None
            return re.sub(r'\\([\\"$`])', r"\1", text[1:-1])
        if kind in ("concatenation", "command_name"):
            parts = [self._literal(c) for c in node.named_children]
            return None if any(p is None for p in parts) else "".join(p for p in parts if p is not None)
        if kind == "number":
            return text
        return None

    def _word(self, node: Node) -> Word:
        return Word(raw=self._text(node), value=self._literal(node))

    # ------------------------------------------------------------------ commands

    def _command(self, node: Node, in_sub: bool) -> None:
        self._scan_substitutions(node, in_sub)
        for child in node.named_children:
            if child.type == "variable_assignment":
                self._visit(child, in_sub)
        name = node.child_by_field_name("name")
        if name is None:
            return
        name_word = self._word(name)
        args = tuple(w for c in node.children_by_field_name("argument") for w in _brace_words(self._word(c)))
        program = program_name(name_word.value) if name_word.value else ""
        cmd = SimpleCommand(
            program=program,
            args=args,
            text=self._text(node),
            cwd=self.cwd,
            redirects=tuple(self._input_redirect(c) for c in node.named_children if c.type == "herestring_redirect"),
            local_program=_local_program(name_word.value),
            dynamic_program=not program,
            in_substitution=in_sub,
        )
        if program in ("printf", "test", "[") and any(w.value == "-v" for w in args):
            self.shell_eval = True
        self._add(cmd)
        if program in ("cd", "pushd", "popd"):
            destination = args[0].value if args else "~"
            if program == "popd" or destination is None or destination == "-" or self.cwd is None:
                self.cwd = None
            elif destination.startswith(("/", "~")):
                self.cwd = destination
            else:
                self.cwd = posixpath.normpath(posixpath.join(self.cwd, destination))

    def _add(self, cmd: SimpleCommand, rounds: int = 0) -> None:
        if cmd.program == "env" and any(
            _hijacks_environment((w.value or w.raw).split("=", 1)[0]) for w in cmd.args if "=" in (w.value or w.raw)
        ):
            self.env_hijack = True
        if cmd.dynamic_program or cmd.local_program or rounds >= MAX_UNWRAP:
            self.commands.append(cmd)
            return
        if cmd.program in SHELLS:
            self._shell(cmd)
            return
        if cmd.program == "eval":
            self.has_substitution = True
            self.commands.append(cmd)
            script = _join_literal(cmd.args)
            if script is not None:
                self._merge_script(script, cmd, "eval")
            return
        inner = _unwrap(cmd)
        if inner is None:
            self.commands.append(cmd)
        else:
            self._add(inner, rounds + 1)

    def _shell(self, cmd: SimpleCommand) -> None:
        script = _shell_script(cmd.args)
        if script is None:
            self.commands.append(cmd)
            return
        if script.value is None or self.depth >= MAX_DEPTH:
            self.opaque_script = True
            self.commands.append(cmd)
            return
        self._merge_script(script.value, cmd, cmd.program)

    def _merge_script(self, script: str, outer: SimpleCommand, wrapper: str) -> None:
        walker = _Walker(script, depth=self.depth + 1)
        walker.cwd = outer.cwd
        inner = walker.run()
        self.parse_error |= inner.parse_error
        self.has_substitution |= inner.has_substitution
        self.decode_then_run |= inner.decode_then_run
        self.pipe_to_shell |= inner.pipe_to_shell
        self.shell_eval |= inner.shell_eval
        self.env_hijack |= inner.env_hijack
        self.opaque_script |= inner.opaque_script
        self.decoded.extend(inner.decoded_scripts)
        for c in inner.commands:
            self.commands.append(
                replace(
                    c,
                    wrapped_by=(*outer.wrapped_by, wrapper, *c.wrapped_by),
                    redirects=c.redirects + outer.redirects,
                    in_substitution=c.in_substitution or outer.in_substitution,
                )
            )

    # ------------------------------------------------------------------ pipelines

    def _check_pipeline(self, stages: list[SimpleCommand]) -> None:
        for i, stage in enumerate(stages):
            if i == 0 or not _reads_code_from_stdin(stage):
                continue
            self.pipe_to_shell = True
            decoders = [s for s in stages[:i] if _decoder(s) is not None]
            if not decoders:
                continue
            self.decode_then_run = True
            payload = _echo_payload(stages[0])
            decoded = _decode(payload, _decoder(decoders[0]) or "") if payload is not None else None
            if decoded is not None and self.depth < MAX_DEPTH:
                self.decoded.append(decoded)
                self._merge_script(decoded, stage, "decode")


# ---------------------------------------------------------------------- helpers (pure)


def _join_literal(words: tuple[Word, ...]) -> str | None:
    values = [w.value for w in words]
    return None if any(v is None for v in values) else " ".join(v for v in values if v is not None)


def _shell_script(args: tuple[Word, ...]) -> Word | None:
    """The script after -c (also inside clusters like -lc or -ec), or None when the shell has no -c."""
    for i, word in enumerate(args):
        value = word.value
        if value is None:
            return None
        if value == "--":
            return None
        if value.startswith("-") and not value.startswith("--") and "c" in value[1:]:
            return args[i + 1] if i + 1 < len(args) else Word("", None)
        if not value.startswith("-") and not value.startswith("+"):
            return None
    return None


def _flags_then_command(
    args: tuple[Word, ...],
    with_value: frozenset[str],
    skip_assignments: bool = False,
    positional_before: int = 0,
) -> tuple[Word, ...] | None:
    """Skip a wrapper's options (and `positional_before` plain arguments) and return the wrapped command's words."""
    i = 0
    positional = positional_before
    while i < len(args):
        value = args[i].value
        if value is None:
            return args[i:]
        if value == "--":
            i += 1
            break
        if skip_assignments and _ASSIGNMENT.match(value):
            i += 1
            continue
        if value.startswith("-") and len(value) > 1:
            i += 2 if value in with_value else 1
            continue
        if positional > 0:
            positional -= 1
            i += 1
            continue
        break
    rest = args[i:]
    return rest or None


_ENV_VALUE = frozenset({"-u", "--unset", "-C", "--chdir", "-P"})
_SUDO_VALUE = frozenset(
    {
        "-u",
        "-g",
        "-C",
        "-D",
        "-h",
        "-p",
        "-r",
        "-t",
        "-U",
        "-T",
        "--user",
        "--group",
        "--chdir",
        "--host",
        "--prompt",
        "--role",
        "--type",
        "--other-user",
        "--command-timeout",
        "--close-from",
    }
)
_TIMEOUT_VALUE = frozenset({"-s", "--signal", "-k", "--kill-after"})
_NICE_VALUE = frozenset({"-n", "--adjustment"})
_XARGS_VALUE = frozenset(
    {
        "-I",
        "-n",
        "-P",
        "-L",
        "-d",
        "-E",
        "-e",
        "-s",
        "-a",
        "--max-args",
        "--max-procs",
        "--delimiter",
        "--arg-file",
        "--replace",
        "--max-lines",
        "--eof",
        "--max-chars",
    }
)
_STDBUF_VALUE = frozenset({"-i", "-o", "-e", "--input", "--output", "--error"})
_NPX_VALUE = frozenset({"-p", "--package", "--from", "--with", "--python", "--call"})
_PLAIN_WRAPPERS = frozenset({"nohup", "command", "builtin", "exec", "time", "doas", "chrt", "ionice", "nocorrect"})
_PACKAGE_RUNNERS = frozenset({"npx", "pnpx", "bunx", "uvx"})


def _unwrap(cmd: SimpleCommand) -> SimpleCommand | None:
    """If `cmd` only wraps another command, return that command (marked with the wrapper); else None."""
    program, args = cmd.program, cmd.args
    rest: tuple[Word, ...] | None
    if program == "env":
        if any(w.value in ("-S", "--split-string") for w in args):
            return None
        rest = _flags_then_command(args, _ENV_VALUE, skip_assignments=True)
    elif program in ("sudo", "doas"):
        rest = _flags_then_command(args, _SUDO_VALUE, skip_assignments=True)
    elif program == "timeout":
        rest = _flags_then_command(args, _TIMEOUT_VALUE, positional_before=1)
    elif program == "nice":
        rest = _flags_then_command(args, _NICE_VALUE)
    elif program == "xargs":
        rest = _flags_then_command(args, _XARGS_VALUE)
    elif program == "stdbuf":
        rest = _flags_then_command(args, _STDBUF_VALUE)
    elif program in _PLAIN_WRAPPERS:
        rest = _flags_then_command(args, frozenset({"-a"}))
    elif program in _PACKAGE_RUNNERS:
        rest = _flags_then_command(args, _NPX_VALUE)
        if rest is not None and rest[0].value is not None:
            package = rest[0].value
            name = package.rsplit("/", 1)[-1] if not package.startswith("@") else package.split("/", 1)[-1]
            name = name.split("@", 1)[0] or name
            rest = (Word(rest[0].raw, name), *rest[1:])
    else:
        return None
    if rest is None:
        return None
    head = rest[0]
    inner_program = program_name(head.value) if head.value else ""
    return SimpleCommand(
        program=inner_program,
        args=rest[1:],
        text=cmd.text,
        cwd=_wrapper_cwd(cmd),
        stdin=cmd.stdin,
        local_program=_local_program(head.value),
        dynamic_program=not inner_program,
        wrapped_by=(*cmd.wrapped_by, program),
        redirects=cmd.redirects,
        in_substitution=cmd.in_substitution,
    )


_INTERPRETERS = frozenset({"python", "python3", "python2", "perl", "ruby", "node", "nodejs", "php", "deno", "bun"})


def _reads_code_from_stdin(cmd: SimpleCommand) -> bool:
    """A shell or interpreter in a pipeline with no script argument runs whatever arrives on stdin."""
    if cmd.program in SHELLS:
        return _shell_script(cmd.args) is None and not any(
            w.value is None or not w.value.startswith("-") for w in cmd.args
        )
    if cmd.program in _INTERPRETERS:
        return all(w.value is not None and (w.value == "-" or w.value.startswith("-")) for w in cmd.args) and not any(
            w.value in ("-c", "-e", "-r", "--eval") for w in cmd.args
        )
    return False


def _decoder(cmd: SimpleCommand) -> str | None:
    """The kind of decoding a pipeline stage does ('base64', 'base32', 'hex', 'other'), or None."""
    values = [v for v in cmd.values if v is not None]

    def has_flag(*names: str, short: str = "") -> bool:
        return any(
            v in names or (short and v.startswith("-") and not v.startswith("--") and short in v[1:]) for v in values
        )

    if cmd.program in ("base64", "gbase64") and has_flag("--decode", short="d"):
        return "base64"
    if cmd.program == "base64" and has_flag("-D"):
        return "base64"
    if cmd.program == "base32" and has_flag("--decode", short="d"):
        return "base32"
    if cmd.program == "xxd" and has_flag(short="r"):
        return "hex"
    if cmd.program == "openssl" and ("base64" in values or "enc" in values) and "-d" in values:
        return "base64"
    if cmd.program in ("uudecode", "gunzip", "zcat", "bunzip2", "xz", "unxz", "rev"):
        return "other"
    return None


def _echo_payload(cmd: SimpleCommand) -> str | None:
    if cmd.program not in ("echo", "printf"):
        return None
    values = [w.value for w in cmd.args]
    if any(v is None for v in values):
        return None
    words = [v for v in values if v is not None]
    while words and cmd.program == "echo" and words[0] in ("-n", "-e", "-E", "-ne", "-en"):
        words = words[1:]
    return " ".join(words) if words else None


def _decode(payload: str, kind: str) -> str | None:
    try:
        match kind:
            case "base64":
                text = payload.strip()
                raw = base64.b64decode(text + "=" * (-len(text) % 4), validate=False)
            case "base32":
                raw = base64.b32decode(payload.strip().upper())
            case "hex":
                raw = bytes.fromhex(payload.strip())
            case _:
                return None
        return raw.decode("utf-8").strip() or None
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None


_ENV_EXEC = frozenset({"PATH", "CDPATH", "BASH_ENV", "ENV", "SHELLOPTS", "BASHOPTS", "PAGER", "EDITOR", "VISUAL"})


def _hijacks_environment(name: str) -> bool:
    return name in _ENV_EXEC or name.startswith(("LD_", "DYLD_", "GIT_", "PYTHON", "PERL", "RUBY", "NODE_"))


def _local_program(value: str | None) -> bool:
    if value is None or "/" not in value:
        return False
    value = value.removeprefix("/proc/self/root")
    directory = value.rsplit("/", 1)[0]
    return directory not in {"/bin", "/sbin", "/usr/bin", "/usr/sbin", "/usr/local/bin", "/usr/local/sbin"}


def _ansi_literal(text: str) -> str | None:
    """Decode literal ANSI-C shell escapes without evaluating any shell text."""
    escapes = {
        "a": "\a",
        "b": "\b",
        "e": "\x1b",
        "E": "\x1b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "v": "\v",
        "\\": "\\",
        "'": "'",
        '"': '"',
    }

    def decode(match: re.Match[str]) -> str:
        token = match.group(1)
        if token[0] in "xuU":
            return chr(int(token[1:], 16))
        if token[0] in "01234567":
            return chr(int(token, 8))
        return escapes.get(token, "\\" + token)

    try:
        return re.sub(r"\\(x[0-9a-fA-F]{1,2}|u[0-9a-fA-F]{1,4}|U[0-9a-fA-F]{1,8}|[0-7]{1,3}|.)", decode, text)
    except ValueError:
        return None


def _wrapper_cwd(cmd: SimpleCommand) -> str | None:
    if cmd.program != "env":
        return cmd.cwd
    for i, word in enumerate(cmd.args):
        value = word.value or ""
        if value in ("-C", "--chdir"):
            target = cmd.args[i + 1].value if i + 1 < len(cmd.args) else None
        elif value.startswith("--chdir="):
            target = value.split("=", 1)[1]
        else:
            continue
        if target is None or cmd.cwd is None:
            return None
        return posixpath.normpath(posixpath.join(cmd.cwd, target))
    return cmd.cwd


def _brace_words(word: Word) -> tuple[Word, ...]:
    # Braces only expand when unquoted. Unsupported range/nested syntax stays
    # opaque so the classifier cannot mistake it for a known safe path.
    quote = ""
    escaped = False
    unquoted_brace = False
    for char in word.raw:
        if escaped:
            escaped = False
        elif char == "\\" and quote != "'":
            escaped = True
        elif char == quote:
            quote = ""
        elif not quote and char in ("'", '"'):
            quote = char
        elif char == "{" and not quote:
            unquoted_brace = True
    if not unquoted_brace:
        return (word,)
    match = re.fullmatch(r"([^{}]*)\{([^{}]*,[^{}]*)\}([^{}]*)", word.raw)
    if match:
        return tuple(Word(word.raw, match[1] + part + match[3]) for part in match[2].split(","))
    return (Word(word.raw, None),)
