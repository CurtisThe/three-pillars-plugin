"""name_kill_scan.py — find process kills by name or pattern in shell and Python.

design: no-kill-by-name (Tasks 1.1, 1.6)

On 2026-10-07 a throwaway test ran `pkill -x claude` and killed every Claude
Code session on the machine. A kill by name or pattern cannot know which
processes it hits; only a kill of a PID the caller started is safe.

`scan_shell(command)` returns one `Hit` per name/pattern kill in a shell
command: a `pkill`/`killall` verb, `fuser -k`, a `kill` fed by `xargs`, a
`kill` of PID `-1`, or a `kill` whose target came from a PID search
(`kill $(pgrep …)`, or a variable assigned from `pgrep`/`pidof`/`ps`/`lsof`/
`fuser` output, also across lines of a file), including one inside a quoted
`"$(…)"` or backquote substitution. A literal `kill <pid>` and a
`kill "$PID"` of a PID the code saved are allowed. Segmenting and verb
resolution (wrappers, `bash -c`, heredocs) come from `reviewer_delete_shell`;
its `Unmodelled` propagates so a caller owns the fail mode.

`scan_text(path, text)` dispatches a file by extension or shebang;
`main()` is the `scan` CLI over a tree of `.py`/`.sh` files (git's tracked and
untracked non-ignored files when the tree is in a work tree). A line carrying
`# tp-allow-fragile: <reason>` is waived, as in the fragility lint.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import namedtuple
from pathlib import Path

from reviewer_delete_lex import cut_heredocs
from reviewer_delete_shell import Unmodelled, parse, resolve

Hit = namedtuple("Hit", "kind where text")

NAME_KILL_VERBS = frozenset({"pkill", "killall"})
SEARCH_VERBS = frozenset({"pgrep", "pidof", "ps", "lsof", "fuser"})
TOKENS = re.compile(r"\b(pkill|killall|pgrep|pidof)\b|xargs[^\n|;&]*\bkill\b|fuser\s[^\n]*-(k|-kill)")
_WAIVER = re.compile(r"#\s*tp-allow-fragile:\s*\S")
_KILL_ARGOPTS = {"-s", "-n", "--signal"}
_DEPTH = 4


def _kill_targets(args):
    """The PID operands of a `kill` argv tail (signal options skipped)."""
    out, i, opts = [], 0, True
    while i < len(args):
        a = args[i]
        if opts and a == "--":
            opts = False
        elif opts and a in _KILL_ARGOPTS:
            i += 1
        elif opts and i == 0 and a.startswith("-") and len(a) > 1 and len(args) > 1:
            pass  # the leading `-SIG` / `-9`
        elif opts and a in ("-l", "-L", "--list"):
            return []
        else:
            out.append(a)
        i += 1
    return out


_SEARCH = r"(?:sudo\s+)?(?:pgrep|pidof|ps|lsof|fuser)\b"
_SUBST = r"(?:\$\(|`)\s*"
# Variables whose value came from a PID search: `V=$(pgrep …)`, `for V in $(pgrep …)`,
# `pgrep … | while read V`, and `W=$V` copies of those.
_TAINT_ASSIGN = re.compile(r"\b([A-Za-z_]\w*)=\(?[\"']?" + _SUBST + _SEARCH)
_TAINT_FOR = re.compile(r"\bfor\s+([A-Za-z_]\w*)\s+in\b[^;\n]*?" + _SUBST + _SEARCH)
_TAINT_READ = re.compile(r"\b(?:pgrep|pidof|ps|lsof|fuser)\b[^;&\n]*\|[^;&\n]*?\bread\s+"
                         r"(?:-\w+\s+)*([A-Za-z_]\w*)")
_COPY = re.compile(r"\b([A-Za-z_]\w*)=[\"']?\$\{?([A-Za-z_]\w*)")
_KILL_SUBST = re.compile(r"\bkill\b[^;&|\n]*?" + _SUBST + _SEARCH)
_VAR_REF = re.compile(r"\$\{?([A-Za-z_]\w*)")


_KILL_WORD = re.compile(r"\b(?:p?kill\w*|fuser)\b")


def _close(text, i):
    """Offset of the `)` that closes a `$(` whose body starts at `i` (len(text) if open)."""
    depth, q, n = 1, None, len(text)
    while i < n:
        c = text[i]
        if q:
            i += c == "\\" and q == '"'
            q = None if c == q else q
        elif c == "\\":
            i += 1
        elif c in "'\"":
            q = c
        elif c in "()":
            depth += 1 if c == "(" else -1
            if not depth:
                return i
        i += 1
    return n


def _substs(text, quotes=True):
    """Bodies of the `$(…)` / backquote substitutions in `text` outside single quotes
    (double-quoted ones included); `quotes=False` reads `'` as a literal."""
    out, i, n, q = [], 0, len(text), None
    while i < n:
        c = text[i]
        if q == "'":
            q = None if c == "'" else q
        elif c == "\\":
            i += 1
        elif text.startswith("$(", i) and not text.startswith("$((", i):
            end = _close(text, i + 2)
            out.append(text[i + 2:end])
            i = end
        elif c == "`":
            end = text.find("`", i + 1)
            end = n if end < 0 else end
            out.append(text[i + 1:end])
            i = end
        elif c == '"' and quotes:
            q = None if q == '"' else '"'
        elif c == "'" and quotes and q is None:
            q = "'"
        i += 1
    return out


def substitution_bodies(command):
    """The command substitutions the shell would run for `command`: those in its
    text and in its unquoted heredoc bodies (a quoted heredoc body is data)."""
    text, docs = cut_heredocs(command)
    return _substs(text) + [b for d in docs if not d.quoted for b in _substs(d.body, False)]


def tainted_vars(text):
    """Names of the variables in `text` that hold PIDs found by a search."""
    names = {m.group(1) for rx in (_TAINT_ASSIGN, _TAINT_FOR, _TAINT_READ)
             for m in rx.finditer(text)}
    copies = _COPY.findall(text)
    for _ in range(len(copies)):
        grown = {dst for dst, src in copies if src in names} - names
        if not grown:
            break
        names |= grown
    return names


def scan_shell(command, depth=0, taint=frozenset()):
    """One `Hit` per name/pattern kill in a shell command; raises `Unmodelled`.
    `taint` adds variables a caller found tainted elsewhere (earlier lines of a file)."""
    if depth > _DEPTH:
        raise Unmodelled("unparseable: nested shell strings too deep")
    taint = set(taint) | tainted_vars(command)
    segs, _ = parse(command)
    # a quoted substitution (`x="$(pkill …)"`) is one opaque word to parse(): scan its body
    hits = [h for body in substitution_bodies(command) if _KILL_WORD.search(body)
            for h in scan_shell(body, depth + 1, taint)]
    for seg in segs:
        r = resolve(seg.argv, seg.heredocs, seg.stdin)
        for text in r.nested:
            hits += scan_shell(text, depth + 1, taint)
        line = " ".join(seg.argv)
        if r.verb in NAME_KILL_VERBS:
            hits.append(Hit("name-kill", r.verb, line))
        elif r.verb == "fuser" and any(a in ("-k", "--kill") or (
                a.startswith("-") and not a.startswith("--") and "k" in a) for a in r.args):
            hits.append(Hit("name-kill", "fuser -k", line))
        elif r.verb == "kill":
            targets = _kill_targets(r.args)
            refs = {v for t in targets for v in _VAR_REF.findall(t)}
            if r.stdin_fed:
                hits.append(Hit("pattern-kill", "xargs kill", line))
            elif "-1" in targets:
                hits.append(Hit("pattern-kill", "kill -1", line))
            elif refs & taint or (any("$" in t or "`" in t for t in targets)
                                  and _KILL_SUBST.search(command)):
                hits.append(Hit("pattern-kill", "kill of searched PIDs", line))
    return hits


def _shell_lines(text, waivers=True):
    """Hits per line of a shell file, with the variables tainted anywhere in the file;
    an unparseable line with a kill token is a hit."""
    hits = []
    taint = tainted_vars("\n".join(line for line in text.splitlines()
                                   if not line.lstrip().startswith("#")))
    for no, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or (waivers and _WAIVER.search(line)):
            continue
        try:
            hits += [h._replace(where=no) for h in scan_shell(stripped, taint=taint)]
        except Unmodelled:
            if TOKENS.search(stripped) or _KILL_SUBST.search(stripped):
                hits.append(Hit("unparseable-kill", no, stripped))
    return hits


def is_python(path, text):
    first = text.split("\n", 1)[0]
    return str(path).endswith(".py") or (first.startswith("#!") and "python" in first)


def scan_text(path, text, waivers=True):
    """Hits for one file's text: Python by extension or shebang, else shell. The
    runtime hook passes `waivers=False`: a comment never unlocks a kill at run time."""
    if is_python(path, text):
        from name_kill_py import scan_python
        waived = {n for n, line in enumerate(text.splitlines(), 1)
                  if waivers and _WAIVER.search(line)}
        return [h for h in scan_python(text) if h.where not in waived]
    return _shell_lines(text, waivers)


def _tree(p):
    """The files under directory `p` a commit could carry: git's tracked plus untracked
    non-ignored files when `p` is in a work tree (a gitignored vendored copy is not
    committed code; a submodule is walked whole), else every file on disk."""
    try:
        out = subprocess.run(["git", "-C", str(p), "ls-files", "-z", "--cached", "--others",
                              "--exclude-standard", "--", "."],
                             capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return p.rglob("*")
    paths = [p / os.fsdecode(rel) for rel in out.split(b"\0") if rel]
    # a submodule is listed as one directory entry: walk its files on disk
    return [f for q in paths for f in (q.rglob("*") if q.is_dir() else (q,))]


def _files(paths):
    for arg in paths:
        p = Path(arg)
        if p.is_dir():
            yield from sorted({f for f in _tree(p) if f.is_file() and f.suffix in (".py", ".sh")
                               and not any(part.startswith(".") or part == "__pycache__"
                                           for part in f.relative_to(p).parts)})
        elif p.is_file():
            yield p


def main(argv=None):
    """`scan <paths…>`: print `path:line kind text` per hit; exit 1 on any, 2 on bad input."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] != "scan" or len(args) < 2:
        print("usage: name_kill_scan.py scan <path>...", file=sys.stderr)
        return 2
    rc = 0
    for f in _files(args[1:]):
        try:
            text = f.read_text(encoding="utf-8")
            hits = scan_text(f, text)
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            print("%s: unreadable: %s" % (f, exc), file=sys.stderr)
            rc = max(rc, 2)
            continue
        for h in hits:
            print("%s:%s %s %s" % (f, h.where, h.kind, str(h.text)[:120]))
            rc = max(rc, 1)
    return rc


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
