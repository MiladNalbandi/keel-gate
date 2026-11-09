"""Built-in rules: turn a tool call into findings (AC-013 to AC-015, AC-020 to AC-024).

Every check only adds findings. combine() later picks the most restrictive one. A program the rules do not know is
"ask", never "allow".

Adapted from keel-v2: engine/keel_engine/runtime/permissions.py (MIT): the git warnings and the rm -r rule.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any

from keel_gate.domain.manifest import ToolSpec
from keel_gate.domain.models import Finding, Tier, Verdict
from keel_gate.domain.shell_ast import SHELLS, ShellParse, SimpleCommand, Word, parse_shell
from keel_gate.domain.sql import classify_sql, looks_like_sql

DEFAULT_PROTECTED_BRANCHES = ("main", "master", "release/*", "production", "prod")


@dataclass(frozen=True)
class ShellContext:
    workspace: str | None
    protected_branches: tuple[str, ...] = DEFAULT_PROTECTED_BRANCHES


def _allow(tier: Tier, rule: str, reason: str) -> Finding:
    return Finding(Verdict.ALLOW, tier, rule, reason)


def _ask(rule: str, reason: str) -> Finding:
    return Finding(Verdict.ASK, Tier.T2, rule, reason)


def _deny(rule: str, reason: str) -> Finding:
    return Finding(Verdict.DENY, Tier.T3, rule, reason)


# ====================================================================== tools


@dataclass(frozen=True)
class Unit:
    """The findings that belong to one simple command (shell), or to the whole call (other tools).

    A custom allow rule only removes "ask" findings of the unit it matches (Amendment A2, AC-197).
    """

    text: str | None
    findings: tuple[Finding, ...]


@dataclass(frozen=True)
class Classification:
    general: tuple[Finding, ...]
    units: tuple[Unit, ...]

    def all(self) -> list[Finding]:
        return [*self.general, *(f for unit in self.units for f in unit.findings)]


def classify_tool(spec: ToolSpec, args: Mapping[str, Any], ctx: ShellContext) -> list[Finding]:
    """Findings for one call of a known tool with valid arguments."""
    return classify_tool_parts(spec, args, ctx).all()


def classify_tool_parts(spec: ToolSpec, args: Mapping[str, Any], ctx: ShellContext) -> Classification:
    if spec.kind == "shell":
        return classify_shell_parts(parse_shell(str(args.get("command", ""))), ctx)
    return Classification((), (Unit(None, (_tool_finding(spec, args),)),))


def _tool_finding(spec: ToolSpec, args: Mapping[str, Any]) -> Finding:
    if spec.sql_arg is not None:
        return _sql_finding(str(args.get(spec.sql_arg, "")))
    if spec.destructive:
        if spec.remote:
            return _deny("remote_destructive", f"'{spec.name}' destroys remote data that undo cannot bring back")
        return _deny("destructive_tool", f"'{spec.name}' is marked destructive")
    if spec.read_only:
        return _allow(Tier.T0, "read_only", f"'{spec.name}' only reads")
    if spec.reversible:
        return _allow(Tier.T1, "reversible", f"'{spec.name}' can be undone")
    return _ask("irreversible", f"'{spec.name}' cannot be undone")


def _sql_finding(text: str) -> Finding:
    kind = classify_sql(text)
    if kind == "destructive":
        return _deny("sql_drop", "the SQL drops, truncates, or changes every row (no WHERE)")
    if kind == "write":
        return _ask("sql_write", "the SQL changes data")
    return _allow(Tier.T0, "sql_read", "the SQL only reads")


# ====================================================================== shell


def classify_shell(parsed: ShellParse, ctx: ShellContext) -> list[Finding]:
    return classify_shell_parts(parsed, ctx).all()


def command_text(cmd: SimpleCommand) -> str:
    """The command as it will really run, after unwrapping: 'terraform destroy -auto-approve'."""
    if cmd.dynamic_program:
        return cmd.text
    return " ".join([cmd.program, *(w.value if w.value is not None else w.raw for w in cmd.args)])


def classify_shell_parts(parsed: ShellParse, ctx: ShellContext) -> Classification:
    general: list[Finding] = []
    if parsed.parse_error:
        general.append(_ask("shell_unparseable", "the command could not be parsed safely"))
    if parsed.has_substitution:
        general.append(
            _ask("shell_substitution", "the command builds parts of itself at run time ($( ), backticks, eval)")
        )
    if parsed.decode_then_run:
        general.append(_ask("decode_then_run", "the command decodes hidden text and runs it"))
    elif parsed.pipe_to_shell:
        general.append(_ask("pipe_to_shell", "the command pipes text into a shell or interpreter"))
    if parsed.opaque_script:
        general.append(_ask("opaque_script", "a script runs whose text cannot be read before it runs"))
    units = tuple(Unit(command_text(cmd), tuple(_classify_command(cmd, ctx))) for cmd in parsed.commands)
    if not general and not units:
        general.append(_allow(Tier.T0, "no_command", "nothing runs"))
    return Classification(tuple(general), units)


READ_ONLY = frozenset(
    {
        "ls",
        "cat",
        "head",
        "tail",
        "grep",
        "egrep",
        "fgrep",
        "rg",
        "ag",
        "ack",
        "wc",
        "pwd",
        "echo",
        "printf",
        "which",
        "whereis",
        "type",
        "file",
        "stat",
        "du",
        "df",
        "tree",
        "sort",
        "uniq",
        "cut",
        "tr",
        "diff",
        "cmp",
        "comm",
        "basename",
        "dirname",
        "realpath",
        "readlink",
        "date",
        "whoami",
        "id",
        "uname",
        "hostname",
        "true",
        "false",
        "test",
        "[",
        "jq",
        "yq",
        "column",
        "nl",
        "md5sum",
        "sha1sum",
        "sha256sum",
        "shasum",
        "cksum",
        "ps",
        "cd",
        "pushd",
        "popd",
        "export",
        "set",
        "less",
        "more",
        "xxd",
        "od",
        "hexdump",
        "strings",
        "sleep",
        "seq",
        "fold",
        "fmt",
        "paste",
        "expand",
        "unexpand",
        "rev",
        "tac",
        "base64",
        "base32",
        "gzip",
        "gunzip",
        "zcat",
    }
)
LOCAL_CHANGE = frozenset({"mkdir", "touch", "cp", "mv", "ln", "chmod", "tee", "install", "rmdir"})
INTERPRETERS = frozenset(
    {
        "python",
        "python3",
        "python2",
        "node",
        "nodejs",
        "perl",
        "ruby",
        "php",
        "deno",
        "bun",
        "rscript",
        "osascript",
        "pwsh",
        "powershell",
        "lua",
    }
)
_INLINE_FLAGS = frozenset({"-c", "-e", "-r", "--eval", "-p", "--print", "-command", "-Command", "-E"})
SQL_CLIENTS = frozenset(
    {
        "psql",
        "mysql",
        "mariadb",
        "sqlite3",
        "sqlcmd",
        "mongosh",
        "mongo",
        "cockroach",
        "clickhouse-client",
        "duckdb",
        "pgcli",
        "mycli",
        "litecli",
    }
)
HTTP_CLIENTS = frozenset({"curl", "wget", "http", "https", "xh", "httpie"})


def _classify_command(cmd: SimpleCommand, ctx: ShellContext) -> list[Finding]:
    if cmd.dynamic_program:
        return [_ask("shell_dynamic_program", "the program name comes from a variable or substitution")]
    out: list[Finding] = []
    if "sudo" in cmd.wrapped_by or "doas" in cmd.wrapped_by:
        out.append(_ask("privilege", "the command runs with elevated privileges"))
    if "xargs" in cmd.wrapped_by and any(w in SHELLS for w in cmd.wrapped_by):
        out.append(_ask("argument_injection", "xargs feeds input into a shell"))
    out.extend(_redirect_findings(cmd, ctx))
    handler = _HANDLERS.get(cmd.program)
    if handler is not None:
        out.extend(handler(cmd, ctx))
    elif cmd.program in READ_ONLY:
        out.append(_allow(Tier.T0, "read_only_command", f"'{cmd.program}' only reads"))
    elif cmd.program in LOCAL_CHANGE:
        out.extend(_local_change(cmd, ctx))
    elif cmd.program in SHELLS:
        out.append(_ask("runs_script", f"'{cmd.program}' runs a script the gate cannot read"))
    elif cmd.program in INTERPRETERS:
        if any(w.value in _INLINE_FLAGS for w in cmd.args):
            out.append(_ask("inline_code", f"'{cmd.program}' runs inline code"))
        else:
            out.append(_ask("runs_code", f"'{cmd.program}' runs a program"))
    else:
        out.append(_ask("unknown_program", f"'{cmd.program}' is not known to be safe"))
    return out


# ---------------------------------------------------------------------- paths


def _resolve(path: str, workspace: str | None) -> str | None:
    """Absolute, normalized path; None when it cannot be known (relative path and no workspace)."""
    if path.startswith("/"):
        resolved = posixpath.normpath(path)
    elif workspace:
        resolved = posixpath.normpath(posixpath.join(workspace, path))
    else:
        return None
    return "/" + resolved.lstrip("/") if resolved.startswith("//") else resolved


def _inside(path: str, workspace: str) -> bool:
    root = posixpath.normpath(workspace)
    return path == root or path.startswith(root.rstrip("/") + "/")


def _outside_reason(word: Word, workspace: str | None) -> str | None:
    """Why a written or deleted path is outside the safe area, or None when it is inside the workspace."""
    value = word.value
    if value is None:
        return "a path built at run time"
    if value.startswith("~"):
        return "the home folder"
    resolved = _resolve(value, workspace)
    if resolved is None:
        return "a path outside the workspace" if ".." in value.split("/") else None
    if workspace is None:
        return f"'{value}'"
    return None if _inside(resolved, workspace) else f"'{value}', outside the workspace"


def _redirect_findings(cmd: SimpleCommand, ctx: ShellContext) -> list[Finding]:
    out: list[Finding] = []
    for redirect in cmd.redirects:
        if redirect.op not in (">", ">>", "&>", "&>>", ">|"):
            continue
        target = redirect.target
        if target.value in ("/dev/null", "/dev/stdout", "/dev/stderr"):
            continue
        reason = _outside_reason(target, ctx.workspace)
        if reason is None:
            out.append(_allow(Tier.T1, "file_write", "writes a file inside the workspace"))
        else:
            out.append(_ask("write_outside_workspace", f"writes to {reason}"))
    return out


def _split_options(args: tuple[Word, ...]) -> tuple[list[str], list[Word]]:
    options: list[str] = []
    targets: list[Word] = []
    ended = False
    for word in args:
        value = word.value
        if not ended and value == "--":
            ended = True
        elif not ended and value is not None and value.startswith("-") and len(value) > 1:
            options.append(value)
        else:
            targets.append(word)
    return options, targets


def _local_change(cmd: SimpleCommand, ctx: ShellContext) -> list[Finding]:
    _, targets = _split_options(cmd.args)
    for word in targets:
        reason = _outside_reason(word, ctx.workspace)
        if reason is not None:
            return [_ask("write_outside_workspace", f"'{cmd.program}' touches {reason}")]
    return [_allow(Tier.T1, "file_change", f"'{cmd.program}' changes files inside the workspace")]


# ---------------------------------------------------------------------- rm and friends

_DRIVE_ROOT = re.compile(r"^[A-Za-z]:[\\/]?$")


def _delete_danger(word: Word, workspace: str | None) -> str | None:
    """Why deleting this target recursively is catastrophic, or None."""
    value = word.value
    if value is None:
        raw = word.raw.strip("\"'")
        if raw.startswith(("$", "`")):
            return f"'{word.raw}', a path from a variable (an empty variable turns it into /)"
        return None
    if value in ("", "/", "/*", "*") and value != "*":
        return "the whole disk"
    if _DRIVE_ROOT.match(value):
        return f"the drive {value}"
    if value.startswith("~"):
        return f"'{value}' in the home folder"
    resolved = _resolve(value, workspace)
    if resolved is None:
        return f"'{value}', outside the workspace" if ".." in value.split("/") else None
    if resolved == "/":
        return "the whole disk"
    if workspace is None:
        return f"'{value}'" if value.startswith("/") else None
    if not _inside(resolved, workspace):
        return f"'{value}', outside the workspace"
    if resolved == posixpath.normpath(workspace):
        return "the whole workspace"
    return None


def _is_recursive(options: list[str]) -> bool:
    for option in options:
        if option in ("-r", "-R", "--recursive"):
            return True
        if not option.startswith("--") and ("r" in option[1:] or "R" in option[1:]):
            return True
    return False


def _rm(cmd: SimpleCommand, ctx: ShellContext) -> list[Finding]:
    options, targets = _split_options(cmd.args)
    recursive = cmd.program == "rimraf" or _is_recursive(options)
    if not recursive:
        for word in targets:
            reason = _outside_reason(word, ctx.workspace)
            if reason is not None:
                return [_ask("rm_outside", f"deletes {reason}")]
        return [_ask("rm_file", "deletes files for good")]
    for word in targets:
        danger = _delete_danger(word, ctx.workspace)
        if danger is not None:
            return [_deny("rm_rf_dangerous", f"recursive delete of {danger}")]
    if not targets:
        return [_ask("rm_recursive", "recursive delete of paths that come from input")]
    return [_ask("rm_recursive", "recursive delete; the files are gone for good")]


def _windows_delete(cmd: SimpleCommand, ctx: ShellContext) -> list[Finding]:
    """rmdir /s, rd /s, del /s: Windows recursive deletes (the Antigravity drive wipe)."""
    switches = [w.value.lower() for w in cmd.args if w.value and re.fullmatch(r"/[A-Za-z]", w.value)]
    targets = [w for w in cmd.args if not (w.value and re.fullmatch(r"/[A-Za-z]", w.value))]
    recursive = "/s" in switches
    for word in targets:
        value = word.value or ""
        if _DRIVE_ROOT.match(value) or (recursive and word.value is None):
            return [_deny("rm_rf_dangerous", f"recursive delete of the drive {value or word.raw}")]
    if recursive:
        return [_ask("rm_recursive", "recursive delete; the files are gone for good")]
    if cmd.program == "rmdir":
        return _local_change(cmd, ctx)
    return [_ask("rm_file", "deletes files for good")]


# ---------------------------------------------------------------------- git

_GIT_GLOBAL_WITH_VALUE = frozenset(
    {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"}
)
_GIT_READ = frozenset(
    {
        "status",
        "log",
        "diff",
        "show",
        "rev-parse",
        "ls-files",
        "ls-tree",
        "blame",
        "describe",
        "shortlog",
        "grep",
        "cat-file",
        "reflog",
        "whatchanged",
        "show-ref",
        "merge-base",
        "count-objects",
        "help",
        "version",
    }
)
_GIT_LOCAL = frozenset(
    {
        "add",
        "commit",
        "fetch",
        "pull",
        "merge",
        "rebase",
        "cherry-pick",
        "revert",
        "init",
        "mv",
        "rm",
        "am",
        "apply",
        "clone",
        "worktree",
        "submodule",
        "notes",
        "bisect",
        "format-patch",
        "archive",
    }
)
_GIT_LOST = {
    "reset": "git reset --hard throws away every uncommitted change in the folder; it cannot be undone.",
    "clean": "git clean deletes the files git does not track; they do not come back.",
    "stash": "This deletes stashed changes for good.",
    "branch": "git branch -D deletes a branch even when its commits are on no other branch.",
    "checkout": "This checkout overwrites files with their committed version: their uncommitted changes are lost.",
    "restore": "git restore puts files back to their committed version: their uncommitted changes are lost.",
    "switch": "This switch throws away the uncommitted changes in the folder.",
}


def _git(cmd: SimpleCommand, ctx: ShellContext) -> list[Finding]:
    args = cmd.args
    out: list[Finding] = []
    i = 0
    while i < len(args):
        value = args[i].value
        if value is None:
            break
        if value in ("-c", "--config-env") or value.startswith(("--config-env=", "--exec-path")):
            out.append(_ask("argument_injection", "git -c / --exec-path can make git run any program"))
        if value in _GIT_GLOBAL_WITH_VALUE:
            i += 2
            continue
        if value.startswith("-"):
            i += 1
            continue
        break
    if i >= len(args) or args[i].value is None:
        return [
            *out,
            _ask("shell_dynamic_program", "the git subcommand is not known before it runs"),
        ]
    sub = args[i].value or ""
    rest = args[i + 1 :]
    values = [w.value or "" for w in rest]
    if any(v.startswith(("--upload-pack", "--receive-pack", "--config")) for v in values) or (
        sub in ("clone", "fetch", "pull") and ("-u" in values or "-c" in values)
    ):
        out.append(_ask("argument_injection", f"git {sub} options can run a program"))
    out.extend(_git_sub(sub, values, rest, ctx))
    return out


def _git_sub(sub: str, values: list[str], rest: tuple[Word, ...], ctx: ShellContext) -> list[Finding]:
    def has(*flags: str) -> bool:
        return any(v in flags for v in values)

    if sub == "push":
        return _git_push(rest, ctx)
    if sub in _GIT_READ:
        return [_allow(Tier.T0, "read_only_command", f"git {sub} only reads")]
    if sub == "branch":
        if has("-D") or (has("-d", "--delete") and has("-f", "--force")):
            return [_ask("git_destructive", _GIT_LOST["branch"])]
        if has(
            "-d",
            "--delete",
            "-m",
            "-M",
            "--move",
            "-c",
            "-C",
            "--copy",
            "-f",
            "--force",
            "-u",
            "--set-upstream-to",
        ):
            return [_allow(Tier.T1, "git_local", "git branch change (recoverable from the reflog)")]
        positional = [v for v in values if not v.startswith("-")]
        if positional:
            return [_allow(Tier.T1, "git_local", "creates a branch")]
        return [_allow(Tier.T0, "read_only_command", "git branch lists branches")]
    if sub == "tag":
        positional = [v for v in values if not v.startswith("-")]
        if has("-d", "--delete"):
            return [_ask("git_destructive", "deletes a tag")]
        if positional and not has("-l", "--list"):
            return [_allow(Tier.T1, "git_local", "creates a tag")]
        return [_allow(Tier.T0, "read_only_command", "git tag lists tags")]
    if sub == "remote":
        positional = [v for v in values if not v.startswith("-")]
        if not positional or positional[0] in ("show", "get-url"):
            return [_allow(Tier.T0, "read_only_command", "git remote only reads")]
        return [_ask("git_config", "changes the repository's remotes")]
    if sub == "config":
        if has("--get", "--get-all", "--get-regexp", "--list", "-l", "--show-origin"):
            return [_allow(Tier.T0, "read_only_command", "git config only reads")]
        return [_ask("git_config", "changes git settings")]
    if sub == "stash":
        action = next((v for v in values if not v.startswith("-")), "push")
        if action in ("list", "show"):
            return [_allow(Tier.T0, "read_only_command", "git stash only reads")]
        if action in ("drop", "clear"):
            return [_ask("git_destructive", _GIT_LOST["stash"])]
        return [_allow(Tier.T1, "git_local", "git stash (recoverable)")]
    if sub == "reset":
        if has("--hard", "--merge", "--keep"):
            return [_ask("git_destructive", _GIT_LOST["reset"])]
        return [_allow(Tier.T1, "git_local", "git reset without --hard keeps the changes")]
    if sub == "clean":
        if has("-n", "--dry-run"):
            return [_allow(Tier.T0, "read_only_command", "git clean dry run")]
        return [_ask("git_destructive", _GIT_LOST["clean"])]
    if sub == "checkout":
        if has("-f", "--force", "--", ".") or "." in values:
            return [_ask("git_destructive", _GIT_LOST["checkout"])]
        return [_allow(Tier.T1, "git_local", "switches branch")]
    if sub == "restore":
        if has("--staged", "-S") and not has("--worktree", "-W"):
            return [_allow(Tier.T1, "git_local", "unstages files")]
        return [_ask("git_destructive", _GIT_LOST["restore"])]
    if sub == "switch":
        if has("--discard-changes", "-f", "--force"):
            return [_ask("git_destructive", _GIT_LOST["switch"])]
        return [_allow(Tier.T1, "git_local", "switches branch")]
    if sub in ("filter-branch", "filter-repo", "update-ref", "gc", "prune", "replace"):
        return [_ask("git_destructive", f"git {sub} can rewrite or delete history")]
    if sub in _GIT_LOCAL:
        return [_allow(Tier.T1, "git_local", f"git {sub} changes only local, recoverable state")]
    return [_ask("unknown_program", f"'git {sub}' is not known to be safe")]


def _protected(branch: str | None, ctx: ShellContext) -> bool:
    if branch is None or branch in ("", "HEAD", "@"):
        return True
    name = branch.removeprefix("refs/heads/")
    return any(fnmatchcase(name, pattern) for pattern in ctx.protected_branches)


def _git_push(rest: tuple[Word, ...], ctx: ShellContext) -> list[Finding]:
    force = delete = mirror = False
    positional: list[str | None] = []
    for word in rest:
        value = word.value
        if value is None:
            positional.append(None)
        elif value in ("-f", "--force") or value.startswith("--force-with-lease"):
            force = True
        elif value == "--mirror":
            mirror = True
        elif value in ("-d", "--delete"):
            delete = True
        elif value.startswith("-") and not value.startswith("--") and len(value) > 1:
            force |= "f" in value[1:]
            delete |= "d" in value[1:]
        elif not value.startswith("-"):
            positional.append(value)
    if mirror:
        return [_deny("git_force_protected", "git push --mirror overwrites every branch on the remote")]
    refspecs = positional[1:]
    targets: list[tuple[str | None, bool]] = []
    for spec in refspecs:
        if spec is None:
            targets.append((None, True))
            continue
        forced = force or delete or spec.startswith("+") or spec.startswith(":")
        destination = spec.lstrip("+").split(":")[-1] if ":" in spec else spec.lstrip("+")
        targets.append((destination or None, forced))
    if not refspecs:
        targets.append((None, force or delete))
    for branch, forced in targets:
        if forced and _protected(branch, ctx):
            label = branch or "the current branch"
            return [_deny("git_force_protected", f"force push or delete of protected branch {label}")]
    if any(forced for _, forced in targets):
        return [_ask("git_force_push", "force push rewrites history on the remote")]
    return [_ask("git_push", "pushes changes to the shared remote")]


# ---------------------------------------------------------------------- argument injection

_FIND_EXEC = frozenset({"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"})


def _find(cmd: SimpleCommand, ctx: ShellContext) -> list[Finding]:
    if any(w.value in _FIND_EXEC for w in cmd.args):
        return [_ask("argument_injection", "find can run commands or delete files (-exec, -delete)")]
    return [_allow(Tier.T0, "read_only_command", "find only lists files")]


def _fd(cmd: SimpleCommand, ctx: ShellContext) -> list[Finding]:
    if any(w.value in ("-x", "--exec", "-X", "--exec-batch") for w in cmd.args):
        return [_ask("argument_injection", "fd -x runs a command for each file")]
    return [_allow(Tier.T0, "read_only_command", "fd only lists files")]


def _go(cmd: SimpleCommand, ctx: ShellContext) -> list[Finding]:
    values = [w.value or "" for w in cmd.args]
    if any(v in ("-exec", "-toolexec") or v.startswith(("-exec=", "-toolexec=")) for v in values):
        return [_ask("argument_injection", "go -exec / -toolexec runs any program")]
    sub = next((v for v in values if not v.startswith("-")), "")
    if sub in ("version", "env", "list", "doc", "help"):
        return [_allow(Tier.T0, "read_only_command", f"go {sub} only reads")]
    return [_ask("runs_code", f"go {sub} builds and runs code")]


def _tar(cmd: SimpleCommand, ctx: ShellContext) -> list[Finding]:
    values = [w.value or "" for w in cmd.args]
    if any(
        v in ("-I", "--to-command", "--use-compress-program")
        or v.startswith(
            (
                "--to-command=",
                "--checkpoint-action",
                "--use-compress-program=",
                "--info-script",
                "--new-volume-script",
            )
        )
        for v in values
    ):
        return [_ask("argument_injection", "tar options can run a program")]
    return _local_change(cmd, ctx)


def _sed(cmd: SimpleCommand, ctx: ShellContext) -> list[Finding]:
    values = [w.value or "" for w in cmd.args]
    if any(v.startswith(("-i", "--in-place")) for v in values):
        return _local_change(cmd, ctx)
    return [_allow(Tier.T0, "read_only_command", "sed without -i only prints")]


def _awk(cmd: SimpleCommand, ctx: ShellContext) -> list[Finding]:
    script = " ".join(w.value or w.raw for w in cmd.args)
    if re.search(r"\bsystem\s*\(|\|\s*getline|print[^;]*>\s*\"", script):
        return [_ask("argument_injection", "the awk script runs commands or writes files")]
    return [_allow(Tier.T0, "read_only_command", "awk only reads")]


def _rsync_ssh(cmd: SimpleCommand, ctx: ShellContext) -> list[Finding]:
    values = [w.value or "" for w in cmd.args]
    if any(v in ("-e", "--rsh") or v.startswith(("--rsh=", "-oProxyCommand", "ProxyCommand")) for v in values):
        return [_ask("argument_injection", f"{cmd.program} options can run a program")]
    return [_ask("network", f"'{cmd.program}' connects to another machine")]


# ---------------------------------------------------------------------- databases and HTTP


def _sql_client(cmd: SimpleCommand, ctx: ShellContext) -> list[Finding]:
    statements = [w.value for w in cmd.args if w.value is not None and looks_like_sql(w.value)]
    if not statements:
        return [_ask("db_client", f"'{cmd.program}' opens a database client")]
    worst = max((_sql_finding(s) for s in statements), key=lambda f: (f.verdict.rank, f.tier.rank))
    return [worst]


_DESTRUCTIVE_WORD = re.compile(r"(?i)(delete|destroy|drop|purge|wipe|terminate|remove)")
_MUTATION = re.compile(r"(?i)\bmutation\b")


def _http(cmd: SimpleCommand, ctx: ShellContext) -> list[Finding]:
    values = [w.value for w in cmd.args]
    method = ""
    bodies: list[str] = []
    for i, value in enumerate(values):
        if value is None:
            continue
        following = values[i + 1] if i + 1 < len(values) else None
        if value in ("-X", "--request", "--method") and following:
            method = following
        elif value.startswith(("--request=", "--method=")):
            method = value.split("=", 1)[1]
        elif value.startswith("-X") and len(value) > 2:
            method = value[2:]
        elif (
            value
            in (
                "-d",
                "--data",
                "--data-raw",
                "--data-binary",
                "--data-urlencode",
                "--json",
                "-F",
                "--form",
                "--body-data",
            )
            and following
        ):
            bodies.append(following)
        elif value.startswith(("--data=", "--data-raw=", "--json=", "--body-data=")):
            bodies.append(value.split("=", 1)[1])
    if cmd.program in ("http", "https", "xh", "httpie"):
        method = next((v for v in values if v and v.isupper() and v.isalpha()), method)
    if method.upper() == "DELETE":
        return [
            _deny(
                "remote_destructive",
                "an HTTP DELETE destroys remote data that undo cannot bring back",
            )
        ]
    if any(_MUTATION.search(b) and _DESTRUCTIVE_WORD.search(b) for b in bodies):
        return [_deny("remote_destructive", "a remote API call that deletes or destroys data")]
    return [_ask("network", f"'{cmd.program}' sends a network request")]


_HANDLERS: dict[str, Callable[[SimpleCommand, ShellContext], list[Finding]]] = {
    "rm": _rm,
    "rimraf": _rm,
    "rd": _windows_delete,
    "del": _windows_delete,
    "rmdir": _windows_delete,
    "git": _git,
    "find": _find,
    "fd": _fd,
    "fdfind": _fd,
    "go": _go,
    "tar": _tar,
    "sed": _sed,
    "gsed": _sed,
    "awk": _awk,
    "gawk": _awk,
    "rsync": _rsync_ssh,
    "ssh": _rsync_ssh,
    "scp": _rsync_ssh,
    **dict.fromkeys(SQL_CLIENTS, _sql_client),
    **dict.fromkeys(HTTP_CLIENTS, _http),
}
