"""fragility_ast.py — shared AST helpers for the fragility lint.

design: fragile-test-prevention (detailed-design-lint §Test-file classification)

`dotted`, `is_test_file` (the runner's own `python_files` globs), `bound_names`
and `md_reads` (+ `is_md_read`, its expression-level predicate). A `.md` read is
a read of a `.md` path, the value of `skill_text.read_skill_text(...)`, or a call
of a same-module helper that returns one (a helper that takes its path is a read
only where the call-site argument is a `.md` string). Pure and stdlib-only; a
broken or unreadable runner config falls back to the defaults.
"""
from __future__ import annotations

import ast
import configparser
import fnmatch
import functools
from pathlib import Path
from typing import Iterator

try:
    import tomllib
except ImportError:  # Python < 3.11: pyproject.toml is simply not consulted
    tomllib = None

DEFAULT_TEST_GLOBS = ("test_*.py", "*_test.py")
_CONFIG_FILES = ("pytest.ini", "setup.cfg", "pyproject.toml")
_INI_SECTIONS = {"pytest.ini": "pytest", "setup.cfg": "tool:pytest"}
_NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
_PATH_CTORS = frozenset({"Path", "pathlib.Path", "PurePath", "pathlib.PurePath",
                         "open", "io.open"})
_PATH_PASSTHROUGH = frozenset({"resolve", "absolute", "expanduser", "open"})
_READ_METHODS = frozenset({"read", "read_text", "read_bytes", "readlines"})
_SKILL_READERS = frozenset({"read_skill_text", "skill_text.read_skill_text"})
_SKILL_PATHS = frozenset({"skill_paths", "skill_text.skill_paths"})
_MAX_HOPS = 8


def dotted(node: ast.AST) -> str | None:
    """`a.b.c` for a Name/Attribute chain; None if anything else is in the chain."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    return ".".join([node.id, *reversed(parts)])


def _python_files(path: Path) -> list[str] | None:
    """`python_files` from one runner config file, or None (absent, unset, broken)."""
    if not path.is_file():
        return None
    try:
        if path.name == "pyproject.toml":
            if tomllib is None:
                return None
            with path.open("rb") as fh:
                value = tomllib.load(fh)["tool"]["pytest"]["ini_options"]["python_files"]
        else:
            parser = configparser.ConfigParser(interpolation=None, strict=False)
            parser.read_string(path.read_text(encoding="utf-8"))
            value = parser.get(_INI_SECTIONS[path.name], "python_files", fallback=None)
    except (OSError, ValueError, KeyError, TypeError, configparser.Error):
        return None
    globs = value.split() if isinstance(value, str) else value
    if not isinstance(globs, list):
        return None
    return [g for g in globs if isinstance(g, str) and g] or None


def runner_globs(directory: str | Path) -> list[str] | None:
    """The `python_files` globs configured in `directory` (pytest.ini, then
    setup.cfg, then pyproject.toml), or None when none of them sets it."""
    for name in _CONFIG_FILES:
        globs = _python_files(Path(directory) / name)
        if globs:
            return globs
    return None


def _globs_above(start: Path) -> list[str] | None:
    """The nearest configured globs walking up from `start`, stopping at a repo root."""
    for directory in (start, *start.parents):
        globs = runner_globs(directory)
        if globs:
            return globs
        if (directory / ".git").exists():
            return None
    return None


def is_test_file(path: str | Path) -> bool:
    """A test module: `conftest.py`, or a basename matching the runner's
    `python_files` globs (else the pytest defaults). Nothing else is."""
    p = Path(path)
    if p.suffix != ".py":
        return False
    if p.name == "conftest.py":
        return True
    resolved = p.resolve()
    globs = _globs_above(resolved.parent) or DEFAULT_TEST_GLOBS
    return any(fnmatch.fnmatchcase(p.name, g)
               or ("/" in g and fnmatch.fnmatchcase(resolved.as_posix(), g))
               for g in globs)


def _own_nodes(scope: ast.AST) -> Iterator[ast.AST]:
    """`scope`'s own nodes in source order, not entering a nested def/class/lambda."""
    stack = list(reversed(scope.body))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, _NESTED_SCOPES):
            stack.extend(reversed(list(ast.iter_child_nodes(node))))


def per_tree(fn):
    """Memoize `fn(tree)` for the one tree last seen (several rules of one lint call
    walk the same parsed module; the next file's tree replaces it). The result is
    materialised to a list so a second caller gets all of it, not a spent iterator."""
    last: list = [None, None]

    @functools.wraps(fn)
    def wrapper(tree):
        if last[0] is not tree:
            last[1] = list(fn(tree))
            last[0] = tree
        return last[1]

    return wrapper


@per_tree
def walk_once(tree: ast.AST) -> Iterator[ast.AST]:
    """`ast.walk(tree)`, walked once per module however many rules ask for it."""
    return ast.walk(tree)


def bound_names(scope: ast.AST) -> dict[str, ast.AST]:
    """Name -> value node for `x = v`, `x: T = v`, `x := v` and `with v as x` in
    one scope (nested scopes excluded; the last binding wins). A `for` or
    comprehension variable over a `skill_paths(...)` value is bound to it too.
    Computed once per scope node, held on it, so every rule of a lint call shares
    one walk; the returned map is read-only (copy before changing it)."""
    cached = scope.__dict__.get("_fragility_bound")
    if cached is None:
        cached = scope.__dict__["_fragility_bound"] = _bound_names(scope)
    return cached


def _bound_names(scope: ast.AST) -> dict[str, ast.AST]:
    bound: dict[str, ast.AST] = {}
    for node in _own_nodes(scope):
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)):
            targets, value = [node.target], node.value
        elif isinstance(node, ast.withitem):
            targets, value = [node.optional_vars], node.context_expr
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            if skill_paths_path(node.iter) is None:
                continue
            targets, value = [node.target], node.iter
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and value is not None:
                bound[target.id] = value
    return bound


def skill_text_path(node: ast.AST) -> str | None:
    """`skills/<name>/SKILL.md` for a call of a `skill_text` reader; `<name>` is
    the first argument when it is a str constant, else a placeholder. None for
    any other node."""
    if not isinstance(node, ast.Call):
        return None
    if dotted(node.func) not in _SKILL_READERS:
        return None
    first = node.args[0] if node.args else None
    name = (first.value if isinstance(first, ast.Constant)
            and isinstance(first.value, str) else "skill")
    return f"skills/{name}/SKILL.md"


def skill_paths_path(node: ast.AST) -> str | None:
    """The same path string for a call of a `skill_paths` name, or a subscript
    off one. None for any other node."""
    if isinstance(node, ast.Subscript):
        return skill_paths_path(node.value)
    if not isinstance(node, ast.Call):
        return None
    if dotted(node.func) not in _SKILL_PATHS:
        return None
    first = node.args[0] if node.args else None
    name = (first.value if isinstance(first, ast.Constant)
            and isinstance(first.value, str) else "skill")
    return f"skills/{name}/SKILL.md"


def _md_str(node: ast.AST, env: dict, hops: int) -> bool:
    if isinstance(node, ast.Name) and hops < _MAX_HOPS and node.id in env:
        return _md_str(env[node.id], env, hops + 1)
    return (isinstance(node, ast.Constant) and isinstance(node.value, str)
            and node.value.endswith(".md"))


def _is_md_path(node: ast.AST, env: dict, hops: int = 0) -> bool:
    """`Path("x.md")`, `open("x.md")`, `base / "x.md"`, `p.open()`, a `skill_paths`
    value, or a name bound to one."""
    if hops >= _MAX_HOPS:
        return False
    if skill_paths_path(node) is not None:
        return True
    if isinstance(node, ast.Subscript):
        return _is_md_path(node.value, env, hops + 1)
    if isinstance(node, ast.Name):
        return node.id in env and _is_md_path(env[node.id], env, hops + 1)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _md_str(node.right, env, hops)
    if isinstance(node, ast.Call):
        if dotted(node.func) in _PATH_CTORS:
            return any(_md_str(arg, env, hops) for arg in node.args)
        if isinstance(node.func, ast.Attribute) and node.func.attr in _PATH_PASSTHROUGH:
            return _is_md_path(node.func.value, env, hops + 1)
    return False


def _helper_call(call: ast.Call, reads, env: dict, hops: int) -> bool:
    """A call of a helper recorded as `name#i`: a read when positional arg `i` is
    a `.md` string."""
    func = call.func
    if not isinstance(func, ast.Name):
        return False
    return any(f"{func.id}#{i}" in reads and i < len(call.args)
               and _md_str(call.args[i], env, hops) for i in range(len(call.args)))


def _is_read(node: ast.AST, env: dict, reads, hops: int = 0) -> bool:
    if hops >= _MAX_HOPS:
        return False
    if isinstance(node, ast.Name):
        return node.id in reads or (node.id in env and _is_read(env[node.id], env, reads, hops + 1))
    if isinstance(node, ast.Subscript):
        return _is_read(node.value, env, reads, hops + 1)
    if not isinstance(node, ast.Call):
        return False
    if skill_text_path(node) is not None:
        return True
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in reads or _helper_call(node, reads, env, hops)
    if not isinstance(func, ast.Attribute):
        return False
    return ((func.attr in _READ_METHODS and _is_md_path(func.value, env))
            or _is_read(func.value, env, reads, hops + 1))


def is_md_read(node: ast.AST, reads=(), env: dict | None = None) -> bool:
    """True for a value read from a `.md` path: a read call, a name or helper
    call in `reads` (from `md_reads`), or a method call or subscript off one.
    `env` (a `bound_names` map) resolves a path held in a name."""
    return _is_read(node, env or {}, reads)


def _positional_params(fn) -> list[str]:
    return [a.arg for a in [*fn.args.posonlyargs, *fn.args.args]]


def _parameterised_helpers(fn, env: dict) -> set[str]:
    """`f"{fn.name}#{i}"` for each positional parameter `i` that makes a returned
    value a `.md` read when it is a `.md` string (and not otherwise)."""
    returns = [n.value for n in _own_nodes(fn) if isinstance(n, ast.Return) and n.value]
    if not returns:
        return set()
    plain = any(_is_read(v, env, ()) for v in returns)
    found: set[str] = set()
    for i, arg in enumerate(_positional_params(fn)):
        if plain:
            break
        bound = {**env, arg: ast.Constant(value="x.md")}
        if any(_is_read(v, bound, ()) for v in returns):
            found.add(f"{fn.name}#{i}")
    return found


def _returning_helpers(module: ast.AST) -> set[str]:
    """Module-level functions that `return` a `.md` read (no further hops), plus a
    `name#i` for one whose read depends on its `i`th positional parameter."""
    module_env = bound_names(module)
    helpers: set[str] = set()
    for fn in module.body:
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        env = {**module_env, **bound_names(fn)}
        if any(isinstance(n, ast.Return) and n.value is not None
               and _is_read(n.value, env, ()) for n in _own_nodes(fn)):
            helpers.add(fn.name)
        else:
            helpers |= _parameterised_helpers(fn, env)
    return helpers


def module_reads_context(module: ast.AST) -> tuple[dict[str, ast.AST], set[str]]:
    """`(bound_names(module), _returning_helpers(module))`: the per-module part of
    `md_reads`, computed once and passed to each `md_reads` call for that module."""
    return dict(bound_names(module)), _returning_helpers(module)


def md_reads(func: ast.AST, module: ast.AST | None = None, context=None) -> set[str]:
    """Names bound to a `.md` read in `func` and at module level (a local
    shadows), plus module-level functions returning one: a call of them is a
    read (one hop). `func` may be the module itself. `context` is the module's
    `module_reads_context`, passed by a caller making one call per function so the
    module is walked once, not once per function."""
    if module is not None and context is None:
        context = module_reads_context(module)
    module_env, helpers = context if module is not None else ({}, set())
    env = dict(module_env)
    env.update(bound_names(func))
    return helpers | {name for name, value in env.items() if _is_read(value, env, helpers)}
