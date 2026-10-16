"""PreToolUse Bash hook for the kill guard: deny a process kill by name or pattern.

design: no-kill-by-name (Task 1.3)

Runs for every session and every agent type (unlike the reviewer-delete hook,
which is scoped). It scans the command itself, inline interpreter code
(`python -c`, `python - <<EOF`, `bash -c`, heredocs) and every script file the
command executes (`python X.py`, `bash X`, `source X`, `./X`, `uv run …`, and
the test files `pytest` would collect from its file/dir arguments or the cwd),
read relative to the segment's cwd. A file is parsed only when its text holds
a kill word (`kill…`, `pkill`, `fuser`, `terminate`, `send_signal`). A hit is denied with the allowed path. When a command (or
one segment of it) cannot be parsed, the hook still reads any `.py`/`.sh` file
named in that segment, then denies only if some scanned text holds a kill
token, so a parser gap never wedges an ordinary session.

Two heredoc shapes are modelled before parsing. A quoted `$(cat <<'EOF' … EOF
)` argument of `git`, `gh` or a `python X.py` script (the commit-message and
PR-body idiom) is data: it becomes a placeholder word, so prose that mentions
`pkill` does not trip the fail-closed fallback. A file the same command writes
from a heredoc (`cat > t.py <<'EOF' … EOF` then `python3 t.py`) is scanned
from that body, since it is not on disk yet when the hook runs; its path is
fixed at the write (a later `cd` does not move it), and the written set is
shared with every nested scan (a substitution body, a `bash -c` text). A
written test file is also one of the files a `pytest` walk over its directory
collects, a directory the same command makes first included. Each command
substitution, quoted ones included (`out="$(python3 t.py)"`), is scanned as a
command.
"""
from __future__ import annotations

import fnmatch
import glob
import json
import os
import re
import sys

_MAX_READ = 256 * 1024
_MAX_FILES = 3000
_PYTHON = re.compile(r"python[0-9.]*$")
_PY_ARGOPTS = {"-W", "-X", "-Q"}
_SH_ARGOPTS = {"-o", "+o", "-O", "+O", "--rcfile", "--init-file"}
_RUNNERS = {"uv", "poetry", "pipenv", "pdm", "hatch"}
# word-bounded: "skill" must not count (every file of a skills repo would be parsed)
_KILLISH = re.compile(r"\b(?:p?kill\w*|fuser|terminate|send_signal)\b")
_SKIP_DIRS = {"node_modules", "__pycache__", "venv"}
_GLOB = re.compile(r"[*?[]")
_CAT_HD = re.compile(r"\$\(\s*cat\s+<<(-?)[ \t]*(?:'(\w+)'|\"(\w+)\"|\\(\w+))[ \t]*\n")
_DATA_WORD = "__TP_HEREDOC_DATA__"
_MESSAGE_VERBS = {"git", "gh"}
_ALLOWED = ("never kill processes by name or pattern; stop only PIDs your own code started "
            "(record Popen PIDs, start them with start_new_session=True, and kill those).")


def _deny(reason):
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": "kill-guard: refused — " + reason}})


def _full(path, cwd):
    return os.path.join(cwd or os.getcwd(), os.path.expanduser(path))


def _read(full):
    if not os.path.isfile(full) or os.path.getsize(full) > _MAX_READ:
        return None
    with open(full, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _is_test_file(name):
    return name == "conftest.py" or (name.endswith(".py") and (
        name.startswith("test_") or name.endswith("_test.py")))


def _collect(root):
    """The test files pytest could collect under `root` (capped, dot-dirs skipped)."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in _SKIP_DIRS]
        out += [os.path.join(dirpath, f) for f in filenames if _is_test_file(f)]
        if len(out) >= _MAX_FILES:
            break
    return out[:_MAX_FILES]


def _expand(arg, cwd, written=()):
    """A glob argument's matches, as the shell expands it before the program
    runs: files on disk plus files this command writes; any other argument (or a
    glob matching nothing, which bash passes through) unchanged."""
    if not _GLOB.search(arg):
        return [arg]
    pattern = os.path.normpath(_full(arg, cwd))
    hits = sorted(glob.glob(pattern, recursive=True)) + [
        f for f in (os.path.normpath(_full(t, cwd)) for t, _ in written)
        if fnmatch.fnmatchcase(f, pattern)]
    return list(dict.fromkeys(hits)) or [arg]


def _pytest_sources(args, cwd, written=()):
    """Files a pytest run collects: its file/dir arguments (or the cwd), walked on
    disk, plus the test files this command writes from a heredoc under a walked
    dir — a dir that is not on disk yet (the command makes it first) included."""
    paths = [e for a in args if not a.startswith("-")
             for e in _expand(a.split("::", 1)[0], cwd, written)]
    new = [os.path.normpath(_full(t, cwd)) for t, _ in written
           if _is_test_file(os.path.basename(t))]

    def under(d):
        return [f for f in new if f.startswith(d.rstrip(os.sep) + os.sep)]

    found = [p for p in paths if p.endswith(".py") or os.path.isdir(_full(p, cwd))
             or under(os.path.normpath(_full(p, cwd)))]
    out = []
    for p in found or ["."]:
        full = os.path.normpath(_full(p, cwd))
        if not os.path.isdir(full) and not under(full):
            out.append(("file", full))
            continue
        out += [("file", f) for f in _collect(full)] + [("file", f) for f in under(full)]
    return list(dict.fromkeys(out))


def _python_sources(args, seg, cwd, written=()):
    """("code", text) / ("file", path) items a python invocation runs."""
    i = 0
    while i < len(args):
        a = args[i]
        if a == "-c":
            return [("code", args[i + 1])] if i + 1 < len(args) else []
        if a == "-m":
            return _pytest_sources(args[i + 2:], cwd, written) if args[i + 1:i + 2] == ["pytest"] else []
        if a == "-":
            break
        if a in _PY_ARGOPTS:
            i += 2
            continue
        if not a.startswith("-"):
            return [("file", _full(_expand(a, cwd, written)[0], cwd))]
        i += 1
    bodies = [h.body for h in seg.heredocs] + ([seg.stdin] if seg.stdin is not None else [])
    return [("code", b) for b in bodies]


def _shell_script(args):
    i = 0
    while i < len(args):
        if args[i] in _SH_ARGOPTS:
            i += 2
        elif args[i] == "--":
            return args[i + 1] if i + 1 < len(args) else None
        elif args[i].startswith(("-", "+")):
            i += 1
        else:
            return args[i]
    return None


def _sources(r, seg, cwd, written=()):
    from reviewer_delete_shell import SHELLS, resolve
    verb, args = r.verb or "", r.args
    if verb in _RUNNERS and args[:1] == ["run"]:
        return _sources(resolve(args[1:], seg.heredocs, seg.stdin), seg, cwd, written)
    if _PYTHON.match(verb):
        return _python_sources(args, seg, cwd, written)
    if verb in ("pytest", "py.test"):
        return _pytest_sources(args, cwd, written)
    if verb in ("source", "."):
        return [("file", _full(args[0], cwd))] if args else []
    if verb in SHELLS and not r.nested:
        script = _shell_script(args)
        return [("file", _full(script, cwd))] if script else []
    word = next((w for w in seg.argv if os.path.basename(w) == verb), "")
    return [("file", _full(word, cwd))] if "/" in word else []


def _named_files(argv, cwd):
    """Fallback for an unparseable segment: every existing `.py`/`.sh` it names."""
    return [("file", _full(w, cwd)) for w in argv if w.endswith((".py", ".sh"))
            and os.path.isfile(_full(w, cwd))]


def _data_heredocs(command):
    """`command` with each quoted `$(cat <<'EOF' … EOF\n)` replaced by a
    placeholder word when every one is an argument of a message verb (`git`,
    `gh`, `python X.py`); None when there is none or one could run as code."""
    from reviewer_delete_shell import parse, resolve
    out, pos = [], 0
    while True:
        m = _CAT_HD.search(command, pos)
        if not m:
            break
        delim = re.escape(m.group(2) or m.group(3) or m.group(4))
        end = re.compile(r"^%s%s[ \t]*(?:\n\s*)?\)" % ("\t*" if m.group(1) else "", delim),
                         re.M).search(command, m.end())
        if not end:
            return None
        out += [command[pos:m.start()], _DATA_WORD]
        pos = end.end()
    if not out:
        return None
    rewritten = "".join(out) + command[pos:]
    try:
        for seg in parse(rewritten)[0]:
            if any(_DATA_WORD in w for w in seg.argv):
                r = resolve(seg.argv, seg.heredocs, seg.stdin)
                srcs = _python_sources(r.args, seg, None) if _PYTHON.match(r.verb or "") else []
                script = len(srcs) == 1 and srcs[0][0] == "file" and _DATA_WORD not in srcs[0][1]
                if r.verb not in _MESSAGE_VERBS and not script:
                    return None
    except Exception:
        return None
    return rewritten


def _written(command, cwd=None):
    """(target, body) for each file the command writes from a heredoc:
    `cat > X <<EOF`, `cat <<EOF >> X`, `tee X <<EOF`. A target is resolved
    against the cwd current at the write (`cd` tracked as in `_scan`)."""
    from reviewer_delete_lex import cut_heredocs
    from reviewer_delete_shell import _REDIRECTS, _SEPARATORS, _items, _prep
    text, docs = cut_heredocs(command)
    out, argv, targets, body, i = [], [], [], None, 0
    items = _items(_prep(text)) + [("op", ";")]
    while i < len(items):
        kind, val = items[i]
        i += 1
        nxt = items[i][1] if i < len(items) and items[i][0] == "w" else None
        if kind == "w":
            argv.append(val)
        elif val in _SEPARATORS:
            name = os.path.basename(argv[0]) if argv else ""
            if body is not None and name in ("cat", "tee"):
                tee = [a for a in argv[1:] if not a.startswith("-")] if name == "tee" else []
                out += [(_full(t, cwd), body) for t in targets + tee]
            if name in ("cd", "pushd") and len(argv) == 2 and "$" not in argv[1]:
                cwd = _full(argv[1], cwd)
            argv, targets, body = [], [], None
        elif val == "<<":
            body = docs.pop(0).body if docs else body
            i += nxt is not None
        elif val in _REDIRECTS or val == "<<<":
            if nxt is not None and val in (">", ">>", ">|"):
                targets.append(nxt)
            i += nxt is not None
    return out


def _scan_source(kind, val, seen, written=()):
    from name_kill_py import scan_python
    from name_kill_scan import scan_text
    texts = [val] if kind == "code" else [_read(val)] + [
        b for t, b in written if os.path.basename(t) == os.path.basename(val)]
    hits = []
    for text in texts:
        if text is None or not _KILLISH.search(text):
            continue
        seen.append(text)
        hits += scan_python(text) if kind == "code" else scan_text(val, text, waivers=False)
    return hits


def _scan(command, cwd, seen, state, depth=0, written=()):
    """Hits for one command string; appends scanned texts to `seen` and sets
    `state["failed"]` when any part of it could not be parsed. `written` carries
    the enclosing command's heredoc-written files into a nested scan."""
    from name_kill_scan import substitution_bodies
    from reviewer_delete_shell import parse, resolve
    hits = []
    segs, _ = parse(command)
    written = list(written) + _written(command, cwd)
    for body in substitution_bodies(command):  # `out="$(python3 t.py)"` runs t.py
        try:
            seen.append(body)
            hits += _scan(body, cwd, seen, state, depth + 1, written)
        except Exception:  # a body without a kill word is data-shaped prose, not a failure
            state["failed"] = state["failed"] or bool(_KILLISH.search(body))
    for seg in segs:
        try:
            r = resolve(seg.argv, seg.heredocs, seg.stdin)
            for text in r.nested:
                seen.append(text)
                hits += _scan(text, cwd, seen, state, depth + 1, written)
            if r.verb in ("cd", "pushd") and len(r.args) == 1 and "$" not in r.args[0]:
                cwd = _full(r.args[0], cwd)
                continue
            sources = _sources(r, seg, cwd, written)
        except Exception:  # one unparseable segment never hides the rest
            state["failed"] = True
            sources = _named_files(seg.argv, cwd)
        for kind, val in sources:
            try:  # one unscannable source never drops the hits of the others
                hits += _scan_source(kind, val, seen, written)
            except Exception:
                state["failed"] = True
    return hits


def run(payload):
    """Return (stdout, exit_code) for one PreToolUse payload."""
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return "", 0
    from name_kill_scan import TOKENS, scan_shell
    command = (payload.get("tool_input") or {}).get("command") or ""
    # the raw command stays in `seen`: any later parse failure still fails closed on it
    seen, state, hits = [command], {"failed": False}, []
    scanned = _data_heredocs(command) or command
    if _KILLISH.search(scanned):
        try:
            hits += scan_shell(scanned)
        except Exception:
            state["failed"] = True
    try:
        hits += _scan(scanned, payload.get("cwd"), seen, state)
    except Exception:
        state["failed"] = True
    if hits:
        first = hits[0]
        return _deny("%s (%s: %s); %s" % (first.kind, first.where, str(first.text)[:80],
                                          _ALLOWED)), 0
    if state["failed"] and any(TOKENS.search(t or "") for t in seen):
        return _deny("could not parse a command that mentions a name kill; " + _ALLOWED), 0
    return "", 0


def main():
    raw = sys.stdin.read()
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        out, code = run(json.loads(raw))
    except Exception as exc:
        try:
            from name_kill_scan import TOKENS
            token = TOKENS.search(raw)
        except Exception:  # the scanner itself failed to import: any kill word denies
            token = _KILLISH.search(raw)
        out, code = (_deny("crashed: %s; %s" % (type(exc).__name__, _ALLOWED)), 0) if token else ("", 0)
    if out:
        print(out)
    sys.exit(code)


if __name__ == "__main__":
    main()
