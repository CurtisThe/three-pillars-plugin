"""Fence-mode verb rules for reviewer_delete_guard (design delete-fence-own-tree).

`classify(..., mode="fence")` limits the destructive set to filesystem deletes.
These helpers hold the git and mv rules so the reviewer classifier stays small;
they take plain data (roots, cwd, a lexer callback) and import nothing from it.
"""
from __future__ import annotations

import os
import re

# What a `$(…)` / backtick may not sit beside in fence mode: a word that could
# delete or move files. Branch/ref words (reset, checkout, stash, ...) are fine,
# and `worktree` counts only as `worktree remove` — a `git worktree list` or a
# commit message about the worktree reaper is not a delete (design 2.1).
DELETE_WORD = re.compile(
    r"\b(rm|rmdir|unlink|shred|mv|rsync|clean|worktree\s+remove)\b"
    r"|-delete|-exec|-execdir|-ok|-okdir")

_GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace",
                   "--config-env", "--super-prefix", "--attr-source"}
_MV_ARGOPTS = {"S", "suffix"}
_MV_TARGET = {"t", "target-directory"}


def strip_single_quoted(text):
    """`text` with each genuinely single-quoted span replaced by `''`.

    The shell never expands anything inside '…', so fence mode reads such a
    span as data when it looks for an expansion beside a delete word. Only a
    quote opened outside double quotes starts a span: an apostrophe inside
    "…" is a literal character, and a backslash escapes the next character in
    both states. `$'…'` (ANSI-C quoting) and an unbalanced quote are kept
    as they are, so the scan reads more text, never less (fail closed)."""
    out, i, n, dq = [], 0, len(text), False
    while i < n:
        c = text[i]
        if c == "\\":
            out.append(text[i:i + 2])
            i += 2
        elif c == '"':
            dq = not dq
            out.append(c)
            i += 1
        elif c == "'" and not dq:
            j = i + 1
            ansi = i > 0 and text[i - 1] == "$"
            while j < n and text[j] != "'":
                j += 2 if ansi and text[j] == "\\" else 1
            if j >= n or ansi:
                out.append(text[i:j + 1])
            else:
                out.append("''")
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _resolve(base, path):
    """Absolute real path of `path` (relative ones against base), or None when
    it cannot be proven (expansion, `~`, or a relative path with no base)."""
    if re.search(r"[$`]", path) or path.startswith("~"):
        return None
    if os.path.isabs(path):
        return os.path.realpath(path)
    return os.path.realpath(os.path.join(base, path)) if base else None


def _in_root(path, roots):
    """True when path equals a root or is inside one."""
    return any(path == r or path.startswith(r + os.sep)
               for r in (os.path.realpath(x) for x in roots))


# A subshell, a pipeline or a background `&` means the cwd a later segment runs
# in is not the one the previous `cd` set, so fence-mode cwd tracking is off.
# Kept importable for callers that only hold raw text; `unknown_separator` is
# the decision the guard actually uses.
UNKNOWN_SEP = re.compile(r"[()]|\||(?<!&)&(?!&)")

# A redirection says where a segment's output goes, not which directory a later
# segment runs in, so the `&` inside `>&` / `2>&1` / `&>` / `&>>` is not a
# separator (design 2.6). A quoted span is data, exactly as the lexer reads it.
_REDIRECT = re.compile(r"\d*<&\d*|\d*>&>?\d*|&>>?|<<<|<<-?|>>?|<>|>\||[<>]")
_QUOTED = re.compile(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"")


def unknown_separator(text):
    """True when the scan holds a separator fence mode cannot carry cwd across:
    `(`, `)`, `|`, `||` or a lone `&`. Redirections and quoted spans are removed
    first, so `cd build && rm -rf out 2>&1` keeps the cwd known."""
    return bool(UNKNOWN_SEP.search(_REDIRECT.sub(" ", _QUOTED.sub(" ", text))))


def cd_target(args, cwd):
    """New cwd for a literal `cd <path>`, or None when it cannot be proven
    (no/extra args, a flag, `-`, `~`, an expansion, or a relative path with no
    known cwd). Absolute and normalised; symlinks are left for the caller."""
    if len(args) != 1:
        return None
    arg = args[0]
    if arg.startswith("-") or arg.startswith("~") or re.search(r"[$`*?{}]", arg):
        return None
    if not os.path.isabs(arg):
        if cwd is None:
            return None
        arg = os.path.join(cwd, arg)
    return os.path.normpath(arg)


def _git_tree(args, cwd):
    """Skip git's global options; return (tree git acts on or None, index of subcommand)."""
    tree, i = os.path.realpath(cwd) if cwd else None, 0
    while i < len(args) and args[i].startswith("-"):
        name, eq, val = args[i].partition("=")
        if name in _GIT_VALUE_OPTS:
            if not eq:
                i += 1
                val = args[i] if i < len(args) else ""
            if name in ("-C", "--work-tree"):
                tree = _resolve(tree, val)
        i += 1
    return tree, i


# `GIT_WORK_TREE` / `GIT_DIR` move the tree git acts on away from the cwd the
# fence checked, whatever value they hold (design 2.7).
_TREE_ENV = re.compile(r"^(GIT_WORK_TREE|GIT_DIR)\+?=")


def tree_env(argv, args):
    """Names of the GIT_WORK_TREE / GIT_DIR assignments before the verb. `args`
    is the tail `resolve` returned, so the words ahead of the verb are the
    keywords, assignments and wrapper words (`env NAME=v …`) that precede it."""
    head = argv[:max(len(argv) - len(args) - 1, 0)]
    return [_TREE_ENV.match(w).group(1) for w in head if _TREE_ENV.match(w)]


def _dry_run(rest):
    return "--dry-run" in rest or any(
        r.startswith("-") and not r.startswith("--") and "n" in r for r in rest)


def fence_git(args, roots, cwd, env=()):
    """Return the refusal reason for a fenced git form, else None. Only
    `git clean` (not a dry run) and `git worktree remove` are fenced. `env` holds
    the tree-moving assignments (`tree_env`): any one makes the tree unprovable."""
    tree, i = _git_tree(args, cwd)
    if i >= len(args):
        return None
    sub, rest = args[i], args[i + 1:]
    if sub == "clean" and not _dry_run(rest):
        verb, target = "git clean", None
    elif sub == "worktree" and next((r for r in rest if not r.startswith("-")), None) == "remove":
        ops = [r for r in rest[rest.index("remove") + 1:] if not r.startswith("-")]
        if len(ops) != 1:
            return "git worktree remove: no provable target"
        verb, target = "git worktree remove", ops[0]
    else:
        return None
    if env:
        return "%s: unprovable tree (%s assigned)" % (verb, env[0])
    if not roots:
        return "%s: no scratch known" % verb
    if tree is None:
        return "%s: unprovable tree (cwd unknown or expansion)" % verb
    if not _in_root(tree, roots):
        return "%s outside scratch: %s" % (verb, tree)
    if target is not None:
        path = _resolve(tree, target)
        if path is None:
            return "%s: unprovable path %r" % (verb, target)
        if not _in_root(path, roots):
            return "%s outside scratch: %s" % (verb, path)
        if tree == path or tree.startswith(path + os.sep):
            return "%s: refusing to remove the checkout cwd is in: %s" % (verb, path)
    return None


def fence_mv(args, operands, cwd):
    """Return (sources, refusal reason or None) for `mv`. Only the sources are
    fenced; `/dev/null` as a destination is denied (it would erase the source)."""
    srcs = operands(args, _MV_ARGOPTS | _MV_TARGET)
    dests = list(operands(args, _MV_ARGOPTS, _MV_TARGET))
    for s in srcs:
        if s in dests:
            dests.remove(s)
    if not dests:  # no -t: the last operand is the destination
        srcs, dests = srcs[:-1], srcs[-1:]
    for d in dests:
        if _resolve(cwd or os.sep, d) == "/dev/null":
            return srcs, "mv: destination /dev/null erases the source"
    return srcs, None
