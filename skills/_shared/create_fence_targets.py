"""create_fence_targets.py — the paths a Bash command creates (design run-scratch-in-fence 1.4).

`shell_targets(command, cwd, env)` returns `(literal_paths, unprovable)`:
absolute, normalised paths a command's redirections, explicit-destination verbs
and temp/cache variable assignments would create, plus the raw words it cannot
prove (an unknown `$VAR`, a command substitution, a glob, a relative path with
no known cwd). It reads the command with `reviewer_delete_guard`'s lexer
(`reviewer_delete_shell`), so a quoted data string is one word and never a
redirect; a lexer failure is unprovable. Simple brace lists and numeric
ranges expand first (`create_fence_braces`, at most 64 words, else unprovable);
`~`, `$NAME`, `${NAME}` and `${NAME:-default}` resolve against `env`; a literal `cd` moves the cwd for
later relative targets unless a pipeline, subshell or `&` makes it unknown.
Inline Python (`python -c`, `python - <<EOF`) is read by `create_fence_py`.
`shell_scan` adds a third value: the `(link, other)` pair when the command makes a
symlink and also creates at or below that link path (the link is not there yet when
the hook resolves paths, so the pair is refused outright).
`has_create_verb(command)` is the cheap prefilter. Stdlib only; nothing runs.
"""
from __future__ import annotations

import os
import re

import run_scratch
from create_fence_braces import expand_braces
from create_fence_py import python_links, python_targets
from delete_fence_py import _PYTHON, _inline_python
from delete_fence_verbs import _git_tree, cd_target, unknown_separator
from reviewer_delete_shell import (_SEPARATORS, Unmodelled, _ASSIGN, _items, _prep,
                                   cut_heredocs, resolve)

ASSIGN_TARGETS = {"TMPDIR", "TMP", "TEMP", *run_scratch.CACHE_VARS}
_CREATE_REDIRECTS = {">", ">>", ">|", "&>", "&>>", "<>"}
_SKIP_REDIRECTS = {"<", "<&", "<<<"}
_DECLARE = {"export", "declare", "typeset", "local", "readonly"}
_VAR = re.compile(r"\$(?:\{([A-Za-z_]\w*)(?::?-([^}$`]*))?\}|([A-Za-z_]\w*))")
_UNPROVABLE_CHARS = re.compile(r"[$`*?\[\]{}]")
_UNKNOWN = "$?"  # prefix that makes a word unprovable (an unknown base dir)
_PREFILTER = re.compile(
    r">|\b(tee|mkdir|touch|cp|mv|install|ln|rsync|dd|curl|wget|tar|unzip|git|venv"
    r"|pip[0-9.]*|ssh-keygen|mktemp|python[0-9.]*|export|env|bash|sh|zsh)\b|\b("
    + "|".join(sorted(ASSIGN_TARGETS)) + r")=")


def has_create_verb(command):
    """False only when `command` cannot create a path this module reads."""
    return bool(_PREFILTER.search(command or ""))


def _expand(word, env):
    """`word` with `~` and known variables expanded, or None when unprovable."""
    if word.startswith("~"):
        head, sep, rest = word.partition("/")
        if head != "~" or not env.get("HOME"):
            return None
        word = env["HOME"] + sep + rest
    missing = []

    def sub(m):
        val = env.get(m.group(1) or m.group(3))
        if val:
            return val
        if m.group(2) is not None:
            return m.group(2)
        missing.append(m.group(0))
        return ""

    out = _VAR.sub(sub, word)
    return None if missing or _UNPROVABLE_CHARS.search(out) else out


def _resolve(word, cwd, env):
    path = _expand(word, env)
    if path is None or not path:
        return None
    if not os.path.isabs(path):
        if cwd is None:
            return None
        path = os.path.join(cwd, path)
    return path


def _flatten(path):
    """`os.path.normpath`, except a `..` right after an existing symlink stays in the literal.

    The kernel climbs from the link's target, not from the link's parent, so collapsing
    it here would hide the real location; the hook then realpaths the raw literal.
    """
    cur = ""
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part != "..":
            cur += "/" + part
        elif cur and os.path.islink(cur):
            return path
        else:
            cur = os.path.dirname(cur)
    return cur or "/"


def _split(args, argopts=(), caps=()):
    """(operands, [(option, value)]) for a getopt-style argv: options in
    `argopts` skip their value, options in `caps` capture it."""
    ops, got, i = [], [], 0
    while i < len(args):
        a = args[i]
        i += 1
        if a == "--":
            ops.extend(args[i:])
            break
        if a.startswith("--"):
            nm, eq, val = a[2:].partition("=")
            if (nm in argopts or nm in caps) and not eq and i < len(args):
                val, i = args[i], i + 1
            if nm in caps:
                got.append((nm, val))
        elif a.startswith("-") and len(a) > 1:
            for k, ch in enumerate(a[1:], 1):
                if ch in argopts or ch in caps:
                    val = a[k + 1:]
                    if not val and i < len(args):
                        val, i = args[i], i + 1
                    if ch in caps:
                        got.append((ch, val))
                    break
        else:
            ops.append(a)
    return ops, got


def _vals(got, *names):
    return [v for n, v in got if n in names and v and v != "-"]


def _copy_like(args, argopts=("S", "suffix")):
    ops, got = _split(args, set(argopts), {"t", "target-directory"})
    tdir = _vals(got, "t", "target-directory")
    return tdir or (ops[-1:] if len(ops) >= 2 else [])


def _install(args):
    if "-d" in args or "--directory" in args:
        return _split(args, {"m", "mode", "o", "owner", "g", "group"})[0]
    return _copy_like(args, ("m", "mode", "o", "owner", "g", "group", "S", "suffix"))


_RSYNC_ARGS = {"e", "f", "rsh", "exclude", "include", "filter", "exclude-from",
               "include-from", "files-from", "backup-dir", "suffix", "port", "bwlimit",
               "partial-dir", "temp-dir", "compare-dest", "chmod", "chown", "log-file"}


def _rsync(args):
    ops = _split(args, _RSYNC_ARGS)[0]
    return [ops[-1]] if len(ops) >= 2 and ":" not in ops[-1] else []


def _tar(args):
    if args and not args[0].startswith("-"):
        args = ["-" + args[0]] + args[1:]
    shorts = [a[1:] for a in args if a.startswith("-") and not a.startswith("--")]
    extract = "--extract" in args or "--get" in args or any("x" in s for s in shorts)
    create = "--create" in args or any("c" in s for s in shorts)
    _ops, got = _split(args, {"b", "T", "X", "H", "N", "g", "I", "files-from",
                              "exclude-from", "format", "newer", "blocking-factor"},
                       {"C", "directory", "f", "file"})
    out = _vals(got, "C", "directory") if extract else []
    return out + (_vals(got, "f", "file") if create else [])


def _mktemp(args):
    args = [a for a in args if a != "--tmpdir"]
    ops, got = _split(args, {"suffix"}, {"p", "tmpdir"})
    pdir = _vals(got, "p", "tmpdir")
    template = ops[0] if ops else None
    if pdir:
        return [os.path.join(pdir[-1], template or "tmp.XXXXXXXXXX")]
    if template and not any(a.startswith("-") and "t" in a[1:] and not a.startswith("--")
                            for a in args):
        return [template]
    return []


def _pip(args):
    if "install" not in args:
        return []
    got = _split(args, {"r", "requirement", "c", "constraint", "e", "editable", "i",
                        "index-url", "extra-index-url", "f", "find-links"},
                 {"t", "target", "prefix", "root"})[1]
    return _vals(got, "t", "target", "prefix", "root")


_GIT_ARGS = {"clone": {"b", "branch", "o", "origin", "c", "config", "depth", "reference",
                       "template", "u", "upload-pack", "j", "jobs", "filter",
                       "separate-git-dir", "shallow-since", "shallow-exclude"},
             "init": {"template", "separate-git-dir", "object-format", "ref-format",
                      "b", "initial-branch", "shared"},
             "add": {"b", "B", "reason"}}


def _git(args, cwd):
    tree, i = _git_tree(args, cwd)
    if i >= len(args):
        return []
    sub, rest = args[i], args[i + 1:]
    if sub == "worktree" and rest[:1] == ["add"]:
        words = _split(rest[1:], _GIT_ARGS["add"])[0][:1]
    elif sub == "init":
        words = _split(rest, _GIT_ARGS["init"])[0][:1]
    elif sub == "clone":
        ops = _split(rest, _GIT_ARGS["clone"])[0]
        if len(ops) >= 2:
            words = [ops[1]]
        else:
            name = os.path.basename(ops[0].rstrip("/")) if ops else ""
            words = [name[:-4] if name.endswith(".git") else name] if name else []
    else:
        return []
    moved = any(a.split("=")[0] in ("-C", "--work-tree") for a in args[:i])
    base = tree if moved else cwd
    return [w if os.path.isabs(w) or w.startswith("~") else
            (_UNKNOWN + w if base is None else os.path.join(base, w)) for w in words]


def _python(args):
    if "-m" in args:
        k = args.index("-m")
        mod, rest = (args[k + 1], args[k + 2:]) if k + 1 < len(args) else ("", [])
        if mod == "venv":
            return _split(rest, {"prompt"})[0]
        if mod == "pip":
            return _pip(rest)
    return []


_VERBS = {
    "tee": lambda a, c: _split(a)[0],
    "mkdir": lambda a, c: _split(a, {"m", "mode", "context"})[0],
    "touch": lambda a, c: _split(a, {"d", "r", "t", "date", "reference"})[0],
    "cp": lambda a, c: _copy_like(a), "mv": lambda a, c: _copy_like(a),
    "ln": lambda a, c: _copy_like(a), "install": lambda a, c: _install(a),
    "rsync": lambda a, c: _rsync(a),
    "dd": lambda a, c: [w[3:] for w in a if w.startswith("of=")],
    "curl": lambda a, c: _vals(_split(a, (), {"o", "output", "output-dir"})[1],
                               "o", "output", "output-dir"),
    "wget": lambda a, c: _vals(_split(a, (), {"O", "output-document", "P",
                                              "directory-prefix", "o", "output-file"})[1],
                               "O", "output-document", "P", "directory-prefix",
                               "o", "output-file"),
    "tar": lambda a, c: _tar(a), "unzip": lambda a, c: _vals(_split(a, (), {"d"})[1], "d"),
    "git": _git, "ssh-keygen": lambda a, c: _vals(_split(a, (), {"f"})[1], "f"),
    "mktemp": lambda a, c: _mktemp(a), "pip": lambda a, c: _pip(a),
}


def _verb_words(verb, args, cwd):
    if _PYTHON.match(verb):
        return _python(args)
    if re.fullmatch(r"pip[0-9.]*", verb):
        verb = "pip"
    fn = _VERBS.get(verb)
    return fn(args, cwd) if fn else []


def _segments(text, docs):
    """[(argv, heredocs, stdin, redirect_words, separator_after)] off the lexer."""
    items, docs, segs = _items(_prep(text)), list(docs), []
    argv, hds, stdin, outs, i = [], [], None, [], 0
    while i < len(items):
        kind, val = items[i]
        i += 1
        nxt = items[i][1] if i < len(items) and items[i][0] == "w" else None
        if kind == "w":
            argv.append(val)
            continue
        if val in _SEPARATORS:
            segs.append((argv, hds, stdin, outs))
            argv, hds, stdin, outs = [], [], None, []
            continue
        if val == "<<":
            if not docs:
                raise Unmodelled("unparseable: heredoc")
            hds.append(docs.pop(0))
        elif val in _CREATE_REDIRECTS or val == ">&":
            if nxt is not None and not (val == ">&" and (nxt.isdigit() or nxt == "-")):
                outs.append(nxt)
        elif val == "<<<":
            stdin = nxt
        elif val not in _SKIP_REDIRECTS:
            raise Unmodelled("unparseable: %r" % val)
        i += nxt is not None
    segs.append((argv, hds, stdin, outs))
    return [s for s in segs if s[0] or s[1] or s[2] is not None or s[3]]


class _Acc:
    def __init__(self):
        self.paths, self.unprovable, self.seen = [], [], []

    def add(self, word, cwd, env, link=False):
        for one in expand_braces(word) or [None]:
            raw = None if one is None else _resolve(one, cwd, env)
            path = None if raw is None else _flatten(raw)
            bucket, item = (self.unprovable, word) if path is None else (self.paths, path)
            if path is not None:
                self.seen.append((path, link, os.path.normpath(raw), raw))
            if item not in bucket:
                bucket.append(item)

    def unprove(self, items):
        self.unprovable += [u for u in items if u not in self.unprovable]

    def conflict(self):
        """(link, other): a symlink path and a different create at or below it."""
        for i, (link, is_link, flat, raw_link) in enumerate(self.seen):
            if not is_link:
                continue
            prefix = link.rstrip("/") + "/"
            for j, (path, other_link, flat_path, raw) in enumerate(self.seen):
                # at or below the link as written, or once `..` is collapsed
                if i != j and (raw.startswith(raw_link.rstrip("/") + "/") or path.startswith(prefix)
                               or flat_path.startswith(prefix)
                               or (flat_path == flat and not other_link)):
                    return link, path
        return None


def _symbolic(args):
    return "--symbolic" in args or any(
        a.startswith("-") and not a.startswith("--") and "s" in a for a in args)


def _assignments(words, acc, cwd, env, update):
    for w in words:
        m = _ASSIGN.match(w)
        if not m:
            continue
        name, value = w[:m.end()].rstrip("+=").split("[")[0], w[m.end():]
        if name in ASSIGN_TARGETS:
            acc.add(value, cwd, env)
        if update:
            exp = _expand(value, env)
            if exp is None:
                env.pop(name, None)
            else:
                env[name] = exp


def _walk(command, cwd, env, acc, depth=0):
    text, docs = cut_heredocs(command)
    scan = text + "".join("\n" + d.body for d in docs if not d.quoted)
    track = not unknown_separator(scan)
    for argv, hds, stdin, outs in _segments(text, docs):
        for w in outs:
            acc.add(w, cwd, env)
        try:
            r = resolve(argv, hds, stdin)
        except Unmodelled:
            _assignments(argv, acc, cwd, env, False)
            acc.unprove([" ".join(argv)] if argv else [])
            continue
        head = argv if r.verb is None else argv[:max(len(argv) - len(r.args) - 1, 0)]
        _assignments(head, acc, cwd, env, r.verb is None)
        if r.verb in _DECLARE:
            _assignments(r.args, acc, cwd, env, True)
        here = None if r.chdir else cwd
        for nested in r.nested:
            if depth < 3:
                _walk(nested, here, dict(env), acc, depth + 1)
        if r.verb in ("cd", "pushd", "popd"):
            exp = _expand(r.args[0], env) if len(r.args) == 1 else None
            cwd = cd_target([exp], cwd) if track and r.verb == "cd" and exp else None
            continue
        if r.verb is None:
            continue
        link = r.verb == "ln" and _symbolic(r.args)
        for w in _verb_words(r.verb, r.args, here):
            acc.add(w, here, env, link)
        if _PYTHON.match(r.verb):
            for src in _inline_python(r.args, hds, stdin):
                paths, unprovable = python_targets(src)
                acc.unprove(unprovable)
                links = python_links(src)
                for p in paths:
                    acc.add(p if not _UNPROVABLE_CHARS.search(p) else _UNKNOWN + p, here, {},
                            p in links)


def shell_scan(command, cwd, env):
    """(literal_paths, unprovable, conflict) for the paths `command` would create."""
    acc = _Acc()
    try:
        _walk(command or "", cwd, dict(env or {}), acc)
    except Unmodelled as exc:
        return [], [str(exc)], None
    return acc.paths, acc.unprovable, acc.conflict()


class Targets(tuple):
    """`(literal_paths, unprovable)` that also carries the link `conflict` pair."""
    conflict = None


def shell_targets(command, cwd, env):
    """(literal_paths, unprovable) for the paths `command` would create; the result's
    `.conflict` is the `(link, other)` pair of `shell_scan`, or None."""
    paths, unprovable, conflict = shell_scan(command, cwd, env)
    out = Targets((paths, unprovable))
    out.conflict = conflict
    return out
