"""delete_fence_py.py — check inline Python for deletes outside the fence roots.

design: delete-fence-own-tree (Task 1.4)

`check_python(source, roots, cwd, shell_check)` walks an inline Python body
(`python -c "…"` / `python - <<EOF`) for delete call sites and returns None when
the source is clean, or the refusal reason. Call sites only, never substrings,
so a data table holding `"rm -rf /"` or a `print("shutil.rmtree('/h')")` is not
a hit.

Denied:
- `shutil.rmtree` / `os.remove` / `os.unlink` / `os.rmdir` / `os.removedirs` and
  `Path(...).unlink()` / `.rmdir()` whose path argument is provably outside the
  roots, or is not a literal at all (a delete verb is present, so the scan
  fails closed);
- a `subprocess` argv or an `os.system`/`os.popen` string whose text the
  caller's `shell_check` (the shell classifier in fence mode) refuses, or a
  computed command this scan cannot read.

A path holding `$` or a backtick is not a literal: bash expands it inside a
double-quoted `-c` string or an unquoted heredoc before Python runs. An
`os.chdir(...)` anywhere in the source makes every relative literal
unprovable, and so does a `cwd=` keyword for that one subprocess call: its
command is judged with the cwd unknown (`shell_check(text, None)`).

A literal path is a `str` constant, `Path("lit")`, `Path("lit") / "lit"` or
`os.path.join` of literals; an f-string, a name or a call is not. A
`SyntaxError` raises `ValueError` — the hook owns the fail mode.

Import aliases (`import shutil as sh`, `from shutil import rmtree as rt`,
`from pathlib import Path`) resolve through the same pattern as
`name_kill_py.py`.
"""
from __future__ import annotations

import ast
import os
import re
import shlex

from fragility_ast import dotted

_PYTHON = re.compile(r"python[0-9.]*$")
_PY_ARGOPTS = {"-W", "-X", "-Q"}

_MODULES = {"shutil", "os", "os.path", "pathlib", "subprocess"}
_PATH_CTORS = {"pathlib.Path", "Path"}
_PATH_METHODS = {"unlink", "rmdir"}
_DELETE_VERBS = {"shutil.rmtree", "os.remove", "os.unlink", "os.rmdir",
                 "os.removedirs"}
_SHELL_CALLS = {"os.system", "os.popen"}
_CHDIR = {"os.chdir", "os.fchdir"}
_CD_VERBS = {"cd", "pushd", "popd"}
_SHELL_EXPANDS = re.compile(r"[$`]")
_SUBPROCESS = {"run", "call", "Popen", "check_call", "check_output", "getoutput",
               "getstatusoutput"}


def _aliases(tree):
    """Local name -> dotted origin, for imports of the modules this scan reads."""
    out = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out.update({a.asname or a.name: a.name for a in n.names if a.name in _MODULES})
        elif isinstance(n, ast.ImportFrom) and n.module in _MODULES:
            out.update({a.asname or a.name: f"{n.module}.{a.name}" for a in n.names})
    return out


def _name(func, aliases):
    """The dotted name of a call target with its leading import alias resolved."""
    name = dotted(func)
    if not name:
        return ""
    head, _, rest = name.partition(".")
    origin = aliases.get(head)
    return (origin + ("." + rest if rest else "")) if origin else name


def _str_of(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _literal_path(node, aliases):
    """The text of a literal path expression, or None when it is not one."""
    text = _str_of(node)
    if text is not None:
        return text
    if isinstance(node, ast.Call):
        name = _name(node.func, aliases)
        if name in _PATH_CTORS and len(node.args) == 1:
            return _literal_path(node.args[0], aliases)
        if name == "os.path.join" and node.args:
            parts = [_str_of(a) for a in node.args]
            return os.path.join(*parts) if all(p is not None for p in parts) else None
        return None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        base = _literal_path(node.left, aliases)
        tail = _str_of(node.right)
        return os.path.join(base, tail) if base is not None and tail is not None else None
    return None


def _is_path_expr(node, aliases):
    """True for `Path(...)` and `Path(...) / …`, so `.unlink()` on any other
    object is not read as a path delete."""
    if isinstance(node, ast.Call):
        return _name(node.func, aliases) in _PATH_CTORS
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _is_path_expr(node.left, aliases)
    return False


def _inside(path, roots, cwd):
    """True when path (relative ones against cwd) is strictly inside a root."""
    if not os.path.isabs(path):
        if cwd is None:
            return False
        path = os.path.join(cwd, path)
    target = os.path.realpath(path)
    return any(target.startswith(os.path.realpath(r) + os.sep) for r in roots)


def _path_verdict(verb, node, aliases, roots, cwd):
    """Refusal reason for a delete call's path argument, else None."""
    text = _literal_path(node, aliases) if node is not None else None
    return _path_verdict_text(verb, text, roots, cwd)


def _path_verdict_text(verb, text, roots, cwd):
    """Refusal reason for an already-resolved delete path, else None."""
    if text is None:
        return "%s: non-literal path (cannot prove target)" % verb
    if _SHELL_EXPANDS.search(text):
        return "%s: shell expansion in path (cannot prove target): %s" % (verb, text)
    if not roots:
        return "%s: no roots known" % verb
    if not _inside(text, roots, cwd):
        return "%s outside roots: %s" % (verb, text)
    return None


def _command_text(node):
    """The command text of a subprocess argv or a shell string, else None."""
    if isinstance(node, (ast.List, ast.Tuple)):
        words = [_str_of(e) for e in node.elts]
        return shlex.join(words) if all(w is not None for w in words) else None
    return _str_of(node)


def _shell_verdict(name, call, shell_check, moved=False):
    """Refusal reason when `call` runs a shell command, else None. After an
    `os.chdir` (`moved`) or with a `cwd=` keyword the command's cwd is unknown."""
    is_sub = name.startswith("subprocess.") and name.split(".", 1)[1] in _SUBPROCESS
    if not (is_sub or name in _SHELL_CALLS):
        return None
    first = call.args[0] if call.args else next(
        (k.value for k in call.keywords if k.arg in ("args", "cmd", "command")), None)
    if first is None:
        return "%s: no provable command" % name
    text = _command_text(first)
    if text is None:
        return "%s: non-literal command (cannot prove target)" % name
    if moved or any(k.arg == "cwd" for k in call.keywords):
        return shell_check(text, None)
    return shell_check(text)


def _bound_names(tree, aliases):
    """Name -> literal path text for `name = Path(<literal>)` / `name = <str>`.

    Task 2.5 resolves a `.unlink()`/`.rmdir()` receiver, so a simple single
    assignment is tracked (a later one to the same name wins). Anything else -
    a parameter, a computed value, a call this scan cannot read - is absent
    from the map, and an absent name fails closed."""
    out = {}
    for n in ast.walk(tree):
        if not isinstance(n, ast.Assign) or len(n.targets) != 1:
            continue
        target = n.targets[0]
        if not isinstance(target, ast.Name):
            continue
        text = _literal_path(n.value, aliases)
        if text is None:
            out.pop(target.id, None)
        else:
            out[target.id] = text
    return out


def _receiver_path(node, aliases, names):
    """The literal path a `.unlink()`/`.rmdir()` receiver denotes, else None.

    A `Path(...)` expression is read directly; a bare name only through a
    simple single assignment this scan saw."""
    if _is_path_expr(node, aliases):
        return _literal_path(node, aliases)
    if isinstance(node, ast.Name):
        return names.get(node.id)
    return None


def _check_call(call, aliases, names, roots, cwd, shell_check, moved=False):
    name = _name(call.func, aliases)
    if name in _DELETE_VERBS:
        return _path_verdict(name, call.args[0] if call.args else None,
                             aliases, roots, cwd)
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr in _PATH_METHODS:
        # Task 2.5: any receiver of a path delete verb counts, not only a
        # visible `Path(...)`. It is refused unless its target is provable.
        text = _receiver_path(func.value, aliases, names)
        return _path_verdict_text("Path." + func.attr, text, roots, cwd)
    return _shell_verdict(name, call, shell_check, moved)


def check_python(source, roots, cwd, shell_check):
    """None when inline Python deletes only inside `roots`, else the reason.

    `shell_check(text)` is the caller's shell classifier, used for a
    `subprocess` argv or an `os.system` string. Raises ValueError on a
    `SyntaxError` (the hook owns the fail mode)."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ValueError("unparseable python: %s" % exc) from exc
    aliases = _aliases(tree)
    names = _bound_names(tree, aliases)
    sites = sorted((n for n in ast.walk(tree) if isinstance(n, ast.Call)),
                   key=lambda n: (n.lineno, n.col_offset))
    moved = any(_name(c.func, aliases) in _CHDIR for c in sites)
    if moved:  # the process cwd moved: no relative literal is provable
        cwd = None
    for call in sites:
        why = _check_call(call, aliases, names, roots, cwd, shell_check, moved)
        if why:
            return why
    return None


def _inline_python(args, heredocs, stdin):
    """The source texts a `python` invocation runs inline (Task 1.5).

    Mirrors `kill_guard_hook._python_sources`: `-c` takes the next word, a bare
    `-` (or no script file) falls back to the segment's heredoc bodies and its
    `<<<` string, a script-file argument or `-m` yields nothing."""
    i = 0
    while i < len(args):
        a = args[i]
        if a == "-c":
            return [args[i + 1]] if i + 1 < len(args) else []
        if a in ("-", "-m"):
            break
        if a in _PY_ARGOPTS:
            i += 2
            continue
        if len(a) > 2 and a.startswith("-") and a.endswith("c"):
            # a short-flag cluster whose last letter is `c` (`-Ic`, `-Bc`):
            # the next word is the script text, exactly as for a bare `-c`.
            return [args[i + 1]] if i + 1 < len(args) else []
        if not a.startswith("-"):
            return []  # a script file: not inline source
        i += 1
    bodies = [h.body for h in heredocs] + ([stdin] if stdin is not None else [])
    return bodies


def inline_sources(command):
    """Every inline Python source text `command` runs (design 1.5).

    Segments are split and resolved with the shared shell layer, so an `env`
    wrapper, option flags, a later `cd` segment and a nested `bash -c "…"` are
    all followed. A segment this layer does not model contributes nothing here
    — the classifier fails closed on it separately."""
    from reviewer_delete_shell import Unmodelled, parse, resolve
    try:
        segs = parse(command)[0]
    except Unmodelled:
        return []
    out = []
    for seg in segs:
        try:
            r = resolve(seg.argv, seg.heredocs, seg.stdin)
        except Unmodelled:
            continue
        if _PYTHON.match(r.verb or ""):
            out += _inline_python(r.args, seg.heredocs, seg.stdin)
        for text in r.nested:
            out += inline_sources(text)
    return out


def moves_cwd(command):
    """True when `command` may run inline Python somewhere other than its
    starting cwd: a `cd`/`pushd`/`popd` segment, an `env -C`/`sudo -D` wrapper,
    either one inside a nested shell string, or a command the shell layer
    cannot parse (fail closed). Read with the lexer, never a raw-text regex."""
    from reviewer_delete_shell import Unmodelled, parse, resolve
    try:
        segs = parse(command)[0]
    except Unmodelled:
        return True
    for seg in segs:
        try:
            r = resolve(seg.argv, seg.heredocs, seg.stdin)
        except Unmodelled:
            return True
        if r.verb in _CD_VERBS or r.chdir or any(moves_cwd(t) for t in r.nested):
            return True
    return False
