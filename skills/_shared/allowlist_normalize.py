"""Normalise a Bash command into per-subcommand prefixes for the allow-list miner.

Fails closed: anything that cannot be read whole becomes one ``unparseable`` Sub
for the entire command, never a prefix. Stdlib only; writes nothing.
"""
import os
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from allowlist_rules import screen  # noqa: E402

_SEPS = frozenset({"&&", "||", ";", "|", "&"})
_ENV = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_HIDDEN = ("$(", "`", "<(", ">(", "${", "<<")
_INTERP = frozenset({"python3", "python", "bash", "sh"})
_SUBVERB = frozenset({"worktree", "stash", "remote"})
_PLAIN_WRAP = frozenset({"time", "nohup", "command", "builtin", "noglob"})
_STDBUF = frozenset({"-oL", "-eL", "-o0"})


@dataclass(frozen=True)
class Sub:
    prefix: str
    kind: str
    screen: "str | None"
    argv: tuple
    root: str = "none"


class _Unparseable(Exception):
    pass


def _split_lines(cmd):
    lines, cur, quote, i = [], [], None, 0
    while i < len(cmd):
        ch = cmd[i]
        if ch == "\\" and quote != "'" and i + 1 < len(cmd):
            cur.append(cmd[i:i + 2])
            i += 2
            continue
        if quote:
            quote = None if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch == "\n":
            lines.append("".join(cur))
            cur = []
            i += 1
            continue
        cur.append(ch)
        i += 1
    lines.append("".join(cur))
    return lines


def _parts(line):
    lex = shlex.shlex(line, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    parts, cur = [], []
    for tok in lex:
        if tok in _SEPS:
            parts.append(cur)
            cur = []
        else:
            cur.append(tok)
    parts.append(cur)
    return [p for p in parts if p]


def _strip_redirects(toks):
    argv, targets = [], []
    i = 0
    while i < len(toks):
        t = toks[i]
        if set(t) <= set("<>&"):
            if argv and argv[-1].isdigit():
                argv.pop()
            if i + 1 >= len(toks):
                raise _Unparseable
            if t in (">", ">>"):
                targets.append(toks[i + 1])
            i += 2
            continue
        if any(c in t for c in "();|") and set(t) <= set("();|&<>"):
            raise _Unparseable
        argv.append(t)
        i += 1
    return argv, targets


def _strip_env_wrappers(argv):
    env = False
    while argv:
        h = argv[0]
        if _ENV.match(h):
            env = True
            argv = argv[1:]
        elif h == "timeout":
            if len(argv) < 3 or not re.fullmatch(r"\d+[smh]?", argv[1]):
                raise _Unparseable
            argv = argv[2:]
        elif h == "nice":
            if argv[1:2] == ["-n"] and len(argv) > 2 and argv[2].isdigit():
                argv = argv[3:]
            elif argv[1:2] and argv[1].startswith("-"):
                raise _Unparseable
            else:
                argv = argv[1:]
        elif h == "stdbuf":
            if len(argv) < 3 or argv[1] not in _STDBUF:
                raise _Unparseable
            argv = argv[2:]
            while argv and argv[0] in _STDBUF:
                argv = argv[1:]
        elif h in _PLAIN_WRAP:
            if argv[1:2] and argv[1].startswith("-"):
                raise _Unparseable
            argv = argv[1:]
        else:
            break
    if not argv:
        raise _Unparseable
    return argv, env


def _root_tag(path):
    if path.startswith("$TP_ROOT/"):
        return "tp-root-text"
    if path.startswith("$"):
        return "other-var"
    return "absolute" if path.startswith("/") else "relative"


def _git_prefix(argv):
    i, c_flag = 1, False
    while i < len(argv) and argv[i] in ("-C", "-c"):
        c_flag = c_flag or argv[i] == "-C"
        i += 2
    if i > len(argv):
        raise _Unparseable
    rest = argv[i:]
    if rest and rest[0].startswith("-"):
        raise _Unparseable
    words = ["git"] + (["-C"] if c_flag else []) + rest[:1]
    if rest and rest[0] in _SUBVERB and len(rest) > 1 and not rest[1].startswith("-"):
        words.append(rest[1])
    return " ".join(words), c_flag


def _prefix_of(argv):
    """Return (prefix, git_c, root) for a stripped argv."""
    head = os.path.basename(argv[0])
    if head == "git":
        prefix, c_flag = _git_prefix(argv)
        return prefix, c_flag, "none"
    if head in ("gh", "tea"):
        words = [t for t in argv[1:] if not t.startswith("-")][:2]
        return " ".join([head] + words), False, "none"
    if head in _INTERP and len(argv) > 1 and not argv[1].startswith("-"):
        path = argv[1]
        if "skills/" in path:
            return f"{head} skills/{path.rsplit('skills/', 1)[1]}", False, _root_tag(path)
        return f"{head} {os.path.basename(path)}", False, _root_tag(path)
    return head, False, "none"


def _outside(target, roots):
    if not target.startswith("/") or target == "/dev/null":
        return False
    return not any(target == r or target.startswith(r.rstrip("/") + "/") for r in roots)


def _sub(toks, roots):
    argv, targets = _strip_redirects(toks)
    argv, env = _strip_env_wrappers(argv)
    prefix, git_c, root = _prefix_of(argv)
    kind = "env-prefixed" if env else ("git-C" if git_c else "rule")
    reason = screen(list(argv))
    if reason is None and any(_outside(t, roots) for t in targets):
        reason = "write:outside-roots"
    return Sub(prefix, kind, reason, tuple(argv), root)


def normalize(cmd, roots=()):
    """Split ``cmd`` into one Sub per compound part; fail closed to one unparseable Sub."""
    words = cmd.split()
    if not words:
        return []
    whole = [Sub(os.path.basename(words[0]), "unparseable", None, ())]
    if any(m in cmd for m in _HIDDEN):
        return whole
    try:
        subs = [_sub(p, roots) for line in _split_lines(cmd) for p in _parts(line)]
    except (ValueError, _Unparseable):
        return whole
    return subs or whole
