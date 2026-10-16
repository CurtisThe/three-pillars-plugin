"""name_kill_py.py — find process kills by name or pattern in Python source.

design: no-kill-by-name (Task 1.2)

Call sites only, never substrings, so a test table holding `"pkill -x claude"`
as data is not a hit. The hits:

- `subprocess` / `os.system` / `os.popen` / `asyncio.create_subprocess_*` with
  a literal command that `name_kill_scan.scan_shell` flags (an argv list whose
  first element is `pkill`/`killall` is a hit even when the rest is computed);
- a scope (module or function, nested functions excluded) that both searches
  for PIDs (`pgrep`/`pidof`/`ps` through subprocess, `psutil.process_iter`,
  `psutil.pids`, or a call to a function of this module that does) and signals
  one it did not start (`os.kill`/`os.killpg` on anything but a `<x>.pid`
  attribute, or `.kill()`/`.terminate()`/`.send_signal()` when the scope used
  psutil);
- `os.kill(-1, …)` / `os.killpg(-1, …)`: every process the user owns.

Import aliases (`import subprocess as sp`, `from subprocess import run as r`),
an `args=` keyword and an absolute-path argv head (`/usr/bin/pkill`) resolve.
"""
from __future__ import annotations

import ast
import os
import shlex

from fragility_ast import dotted
from name_kill_scan import NAME_KILL_VERBS, SEARCH_VERBS, TOKENS, Hit, Unmodelled, scan_shell

_SUBPROCESS = {"run", "call", "Popen", "check_call", "check_output", "getoutput",
               "getstatusoutput"}
_SHELL_CALLS = {"os.system", "os.popen", "asyncio.create_subprocess_shell",
                "commands.getoutput"}
_EXEC_CALLS = {"asyncio.create_subprocess_exec", "os.execvp", "os.execlp", "os.spawnlp"}
_PSUTIL_SEARCH = {"psutil.process_iter", "psutil.pids"}
_SIGNAL_METHODS = {"kill", "terminate", "send_signal"}
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
_MODULES = {"subprocess", "os", "psutil", "asyncio", "commands"}


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


def _literal(node):
    """The text of a str constant or f-string (placeholders as `X`), else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "X" for v in node.values)
    return None


def _base(word):
    return os.path.basename(word) if word else word


def _argv(node):
    """(first word, joined command or None) of a command argument."""
    if isinstance(node, (ast.List, ast.Tuple)) and node.elts:
        words = [_literal(e) for e in node.elts]
        joined = shlex.join(words) if all(w is not None for w in words) else None
        return _base(words[0]), joined
    text = _literal(node)
    if text is None:
        return None, None
    try:
        head = shlex.split(text)[0] if text.strip() else None
    except ValueError:
        head = text.split()[0] if text.split() else None
    return _base(head), text


def _shell_hits(command):
    try:
        return scan_shell(command)
    except Unmodelled:
        return [Hit("unparseable-kill", None, command)] if TOKENS.search(command) else []


def _command_of(call, name):
    """(argv head, command text) when `call` runs a command, else (None, None)."""
    if name in _EXEC_CALLS:
        words = [_literal(a) for a in call.args]
        joined = shlex.join(words) if words and all(w is not None for w in words) else None
        return (_base(words[0]) if words else None), joined
    is_sp = name.startswith("subprocess.") and name.split(".", 1)[1] in _SUBPROCESS
    if not (is_sp or name in _SHELL_CALLS):
        return None, None
    first = call.args[0] if call.args else next(
        (k.value for k in call.keywords if k.arg in ("args", "cmd", "command")), None)
    return _argv(first) if first is not None else (None, None)


def _is_minus_one(node):
    return (isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub)
            and isinstance(node.operand, ast.Constant) and node.operand.value == 1)


def _own_nodes(scope):
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, _SCOPES):
            stack.extend(ast.iter_child_nodes(node))


def _searches(node, aliases, searchers):
    name = _name(node.func, aliases)
    head, _ = _command_of(node, name)
    return head in SEARCH_VERBS or name in _PSUTIL_SEARCH or (
        bool(name) and name.rsplit(".", 1)[-1] in searchers)


def _searchers(tree, aliases):
    """Names of this module's functions whose own body searches for PIDs."""
    return {fn.name for fn in ast.walk(tree)
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                isinstance(n, ast.Call) and _searches(n, aliases, ()) for n in _own_nodes(fn))}


def _scan_scope(scope, aliases, searchers):
    hits, search, psutil_used, signals = [], False, False, []
    for node in _own_nodes(scope):
        if not isinstance(node, ast.Call):
            continue
        name = _name(node.func, aliases)
        head, command = _command_of(node, name)
        if head in NAME_KILL_VERBS:
            hits.append(Hit("name-kill", node.lineno, head))
        elif command is not None:
            hits += [h._replace(where=node.lineno) for h in _shell_hits(command)]
        search = search or _searches(node, aliases, searchers)
        psutil_used = psutil_used or name in _PSUTIL_SEARCH
        if name in ("os.kill", "os.killpg") and node.args:
            target = node.args[0]
            if _is_minus_one(target):
                hits.append(Hit("pattern-kill", node.lineno, name + "(-1)"))
            elif not (isinstance(target, ast.Attribute) and target.attr == "pid"):
                signals.append((node.lineno, name))
        elif isinstance(node.func, ast.Attribute) and node.func.attr in _SIGNAL_METHODS:
            signals.append((node.lineno, "." + node.func.attr + "()"))
    for line, what in signals:
        if search and (what.startswith("os.") or psutil_used):
            hits.append(Hit("search-then-signal", line, what))
    return hits


def scan_python(source):
    """One `Hit` per name/pattern kill call site; `where` is the line number."""
    return scan_tree(ast.parse(source))


def scan_tree(tree):
    """`scan_python` over an already-parsed module (the fragility lint's visitor)."""
    aliases = _aliases(tree)
    searchers = _searchers(tree, aliases)
    scopes = [tree] + [n for n in ast.walk(tree) if isinstance(n, _SCOPES)]
    hits = [h for scope in scopes for h in _scan_scope(scope, aliases, searchers)]
    return sorted(set(hits), key=lambda h: (h.where or 0, h.kind))
