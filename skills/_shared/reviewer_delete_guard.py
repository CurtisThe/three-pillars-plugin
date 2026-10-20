"""Pure classifier for the reviewer-delete-guard: may a read-mostly reviewer
agent run this Bash command? Deletes are allowed only strictly inside the
agent's own scratch; anything it cannot prove is refused (fail closed)."""
from __future__ import annotations

import glob
import os
import re
from collections import namedtuple

from delete_fence_verbs import (DELETE_WORD, cd_target, fence_git, fence_mv,
                                strip_single_quoted, tree_env, unknown_separator)
from reviewer_delete_shell import (SEMI, WRAPPERS, SHELLS, Unmodelled, cut_heredocs,
                                   parse, resolve)

Verdict = namedtuple("Verdict", "allowed reason")

DESTRUCTIVE_WORD = re.compile(
    r"\b(rm|rmdir|unlink|shred|mv|rsync|clean|reset|restore|checkout|switch|worktree|"
    r"stash|branch|push)\b|-delete|-exec|-execdir|-ok|-okdir")
_EXPANSION = re.compile(r"\$\(|`|<\(|>\(")
RMLIKE = {"rm", "rmdir", "unlink", "shred"}
_ARGOPTS = {"shred": {"n", "s", "iterations", "size", "random-source"},
            "mv": {"S", "suffix"},
            "rsync": {"e", "f", "rsh", "exclude", "include", "filter", "exclude-from",
                      "include-from", "files-from", "backup-dir", "suffix", "port",
                      "bwlimit", "partial-dir", "temp-dir", "compare-dest"}}
_FIND_TERMINATORS = {";", "+", SEMI}
_DEPTH = 3
_NO_SCRATCH = "no scratch known"


def _refuse(reason):
    return Verdict(False, reason)


def _roots(scratch):
    """Normalise a scratch spec (one root, or a list of roots) to a list."""
    if scratch is None:
        return []
    return list(scratch) if isinstance(scratch, (list, tuple)) else [scratch]


def _inside(path, scratch, cwd):
    """True when path (relative ones against cwd) is strictly inside a root."""
    if not os.path.isabs(path):
        if cwd is None:
            return False
        path = os.path.join(cwd, path)
    target = os.path.realpath(path)
    return any(target.startswith(os.path.realpath(r) + os.sep) for r in _roots(scratch))


def _operand_ok(op, scratch, cwd):
    """Return None when op is provably inside scratch, else the reason."""
    if not _roots(scratch):
        return _NO_SCRATCH
    if re.search(r"[${}`]", op) or op.startswith("~"):
        return "unprovable operand %r (expansion)" % op
    if not os.path.isabs(op) and cwd is None:
        return "unprovable operand %r (cwd unknown)" % op
    if re.search(r"[*?\[]", op):
        full = op if os.path.isabs(op) else os.path.join(cwd, op)
        if ".." in full.split(os.sep):
            return "unprovable operand %r (glob with ..)" % op
        head = re.split(r"[*?\[]", full, maxsplit=1)[0]
        base = os.path.realpath(os.path.dirname(head) or os.sep)
        if not any(base == os.path.realpath(r) or
                   base.startswith(os.path.realpath(r) + os.sep) for r in _roots(scratch)):
            return "glob %r outside scratch" % op
        for hit in glob.glob(full):
            if not _inside(hit, scratch, cwd):
                return "glob %r matches outside scratch" % op
        return None
    if not _inside(op, scratch, cwd):
        return "outside scratch: %s" % op
    return None


def _operands(args, argopts=(), captured=()):
    ops, i = [], 0
    while i < len(args):
        a = args[i]
        i += 1
        if a == "--":
            ops.extend(args[i:])
            break
        if a.startswith("--"):
            nm, eq, val = a[2:].partition("=")
            if nm in captured and eq:
                ops.append(val)
            elif nm in argopts or nm in captured:
                if not eq and i < len(args):
                    if nm in captured:
                        ops.append(args[i])
                    i += 1
        elif a.startswith("-") and len(a) > 1:
            for k, ch in enumerate(a[1:], 1):
                if ch in argopts or ch in captured:
                    val = a[k + 1:]
                    if not val and i < len(args):
                        val = args[i]
                        i += 1
                    if ch in captured and val:
                        ops.append(val)
                    break
        else:
            ops.append(a)
    return ops


def _check_operands(verb, ops, scratch, cwd):
    if not ops:
        return _refuse("%s: no provable target" % verb)
    if callable(scratch):  # the hook's lazy lookup: resolved only when a delete needs it
        scratch = scratch()
    if not _roots(scratch):
        return _refuse("%s: %s" % (verb, _NO_SCRATCH))
    for op in ops:
        why = _operand_ok(op, scratch, cwd)
        if why:
            return _refuse("%s outside scratch: %s" % (verb, why))
    return None


def _short(rest, ch):
    return any(r.startswith("-") and not r.startswith("--") and ch in r for r in rest)


def _checkout_detach(rest):
    """True only for `checkout [-q|--quiet] --detach <one rev>` (keeps the tree)."""
    words = [r for r in rest if r not in ("-q", "--quiet")]
    revs = [r for r in words if r != "--detach"]
    return words.count("--detach") == 1 and len(revs) == 1 and not revs[0].startswith("-")


def _git(args):
    """Return the refusal reason for a destructive git form, else None."""
    i = 0
    while i < len(args) and args[i].startswith("-"):
        takes = args[i] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace",
                            "--config-env", "--super-prefix", "--attr-source")
        i += 2 if takes else 1
    if i >= len(args):
        return None
    sub, rest = args[i], args[i + 1:]
    first = next((r for r in rest if not r.startswith("-")), None)
    if sub == "clean" and not (_short(rest, "n") or "--dry-run" in rest):
        return "git clean"
    if sub == "reset" and "--hard" in rest:
        return "git reset --hard"
    if sub == "checkout" and _checkout_detach(rest):
        return None
    if sub in ("restore", "rm", "checkout"):
        return "git " + sub
    if sub == "switch" and (_short(rest, "f") or {"--force", "--discard-changes"} & set(rest)):
        return "git switch --force"
    if sub == "worktree" and first in ("remove", "prune"):
        return "git worktree " + first
    if sub == "branch" and (_short(rest, "d") or _short(rest, "D") or "--delete" in rest):
        return "git branch delete"
    if sub == "push" and (_short(rest, "d") or {"--delete", "--prune", "--mirror"} & set(rest)
                          or any(r.startswith((":", "+:")) for r in rest)):
        return "git push delete"
    if sub == "stash" and not (rest and rest[0] in ("list", "show")):
        return "git stash"
    return None


def _exec_destructive(cmd):
    if not cmd:
        return False
    if os.path.basename(cmd[0]) in set(WRAPPERS) | SHELLS:
        return True
    try:
        verb = resolve(cmd).verb
    except Unmodelled:
        return True
    return verb in RMLIKE | {"mv", "rsync", "git", "find"}


def _exec_check(kind, cmd, starts, scratch, cwd, depth, mode):
    """Check find's exec'd command like any segment; `{}` is a path under a start
    (`-execdir`/`-okdir` run in the found file's directory: cwd unknown)."""
    run_cwd = cwd if kind in ("-exec", "-ok") else None
    for start in starts:
        root = os.path.join(cwd, start) if cwd is not None else start
        words = [w.replace("{}", os.path.join(root, "__tp_found__")) for w in cmd]
        r = resolve(words)
        here = None if r.chdir else run_cwd
        for text in r.nested:
            bad = _check(text, scratch, {"cwd": here, "mode": mode}, depth + 1)
            if bad:
                return bad
        bad = _check_verb(r, scratch, here, depth, mode, tree_env(words, r.args))
        if bad:
            return bad
    return None


def _find(args, scratch, cwd, depth, mode):
    i, hard = 0, False
    while i < len(args):
        a = args[i]
        if a == "-L":
            hard = True
        if a in ("-H", "-L", "-P") or re.fullmatch(r"-O\d*", a):
            i += 1
        elif a == "-D":
            i += 2
        else:
            break
    starts = []
    while i < len(args) and not args[i].startswith(("-", "(", ")", "!")):
        starts.append(args[i])
        i += 1
    starts = starts or ["."]
    expr, destructive, j = args[i:], False, 0
    while j < len(expr):
        w = expr[j]
        if w == "-delete":
            destructive = True
        elif w in ("-follow", "-files0-from"):
            hard = True
        elif w in ("-exec", "-execdir", "-ok", "-okdir"):
            k, cmd = j + 1, []
            while k < len(expr) and expr[k] not in _FIND_TERMINATORS:
                cmd.append(expr[k])
                k += 1
            destructive = destructive or _exec_destructive(cmd)
            bad = _exec_check(w, cmd, starts, scratch, cwd, depth, mode)
            if bad:
                return bad
            j = k
        j += 1
    if not destructive:
        return None
    if hard:
        return _refuse("find delete with -L/-follow/-files0-from")
    if mode == "fence" and cwd is not None:
        # `find` never removes its own start directory, so a start of `.` is safe
        # at a root for `-delete` as well as for `-exec` (design 2.3)
        if os.path.realpath(cwd) in {os.path.realpath(r) for r in _roots(
                scratch() if callable(scratch) else scratch)}:
            starts = [s for s in starts if os.path.normpath(s) != "."]
    return _check_operands("find", starts, scratch, cwd) if starts else None


def _check_verb(r, scratch, cwd, depth=0, mode="reviewer", env=()):
    verb, args = r.verb, r.args
    if verb in RMLIKE or verb == "mv":
        if args and all(a in ("--help", "--version") for a in args):
            return None
        if r.stdin_fed:
            return _refuse("%s: operands from stdin" % verb)
        if verb == "mv" and mode == "fence":
            ops, why = fence_mv(args, _operands, cwd)
            if why:
                return _refuse(why)
        else:
            ops = _operands(args, _ARGOPTS.get(verb, ()),
                            {"t", "target-directory"} if verb == "mv" else ())
        return _check_operands(verb, ops, scratch, cwd)
    if verb == "rsync":
        if not any(a.startswith("--del") or a == "--remove-source-files" for a in args):
            return None
        if r.stdin_fed:
            return _refuse("rsync: operands from stdin")
        ops = _operands(args, _ARGOPTS["rsync"])
        if any(":" in op for op in ops):
            return _refuse("rsync: unprovable remote operand")
        return _check_operands("rsync", ops, scratch, cwd)
    if verb == "find":
        return _find(args, scratch, cwd, depth, mode)
    if verb == "git":
        why = _git(args) if mode != "fence" else fence_git(
            args, _roots(scratch() if callable(scratch) else scratch), cwd, env)
        return _refuse(why) if why else None
    return None


def _fence_prescan(command):
    """The expansion scan text for fence mode: the command with its genuinely
    single-quoted spans stripped, plus each unquoted heredoc body unstripped."""
    text, docs = cut_heredocs(command)
    return strip_single_quoted(text) + "".join("\n" + d.body for d in docs if not d.quoted)

def _check(command, scratch, state, depth):
    if depth > _DEPTH:
        return _refuse("unparseable: nested shell strings too deep")
    try:
        segs, scan = parse(command)
        word = DELETE_WORD if state["mode"] == "fence" else DESTRUCTIVE_WORD
        # fence mode follows a literal `cd`; a subshell / pipeline / `&` or an
        # unprovable cd target makes the cwd unknown instead (design 1.3).
        track = state["mode"] == "fence" and not unknown_separator(scan)
        # Fence mode reads single-quoted text as data: the shell expands nothing
        # inside '…', so a backtick written there cannot pair with a delete word
        # (design 2.1). The strip is quote-aware and skips unquoted heredoc
        # bodies, where a quote is a plain character. Reviewer mode strips nothing.
        pre = scan if state["mode"] != "fence" else _fence_prescan(command)
        if _EXPANSION.search(pre) and word.search(pre):
            return _refuse("unparseable: expansion alongside a destructive word")
        for seg in segs:
            r = resolve(seg.argv, seg.heredocs, seg.stdin)
            for text in r.nested:
                bad = _check(text, scratch, state, depth + 1)
                if bad:
                    return bad
            if r.verb in ("cd", "pushd", "popd"):
                state["cwd"] = cd_target(r.args, state["cwd"]) if track and r.verb == "cd" else None
                continue
            bad = _check_verb(r, scratch, None if r.chdir else state["cwd"], depth,
                              state["mode"], tree_env(seg.argv, r.args))
            if bad:
                return bad
    except Unmodelled as exc:
        return _refuse(str(exc))
    return None


def classify(command, *, scratch, cwd, mode="reviewer"):
    """Return Verdict(allowed, reason) for a Bash command from a scoped agent.
    mode="fence" limits the destructive set to filesystem deletes."""
    bad = _check(command, scratch, {"cwd": cwd, "mode": mode}, 0)
    return bad or Verdict(True, "allowed")
