"""fragility_rules_flag.py — the flag-only fragility rules.

design: fragile-test-prevention (detailed-design-lint §Rule registry)

Flag-family rules of `fragility_registry.RULES`: they are reported, and gate only when a
repo's gating set names them. Test side: `md-read-assert`, `line-literal`, `doc-line-cap`, `wall-clock`; production side: `prose-regex`.
`visit(tree, path, ctx)` runs the flag-family rules whose side matches `path` and returns
`Finding(rule_id, line, end_line)` sorted by line (the flagged assert's own span); the
caller applies waivers and the gating set, and `ctx` is unused here.

A `.md` read is traced by `fragility_ast.md_reads` in the assert's scope, at module level
and through a one-hop helper; a parameter shadows a module-level name. A value that cannot
be traced to a `.md` read (a parsed structure, a registry-derived set) is never flagged.
"""
from __future__ import annotations

import ast
from typing import Iterator

from fragility_ast import (bound_names, dotted, is_md_read, is_test_file, md_reads,
                           module_reads_context, per_tree, walk_once)
from fragility_registry import RULES, gating_set
from fragility_rules_gating import Finding

_NESTED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
_RE_CALLS = frozenset({"search", "match", "fullmatch", "findall"})
_PREFIX_CALLS = frozenset({"startswith", "endswith"})
_LINE_NAMES = frozenset({"lineno", "end_lineno", "line", "line_range", "line_number"})
_COMPARES = (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)


def _own_nodes(scope: ast.AST) -> Iterator[ast.AST]:
    """`scope`'s own nodes, not entering a nested def, class or lambda."""
    stack = list(scope.body)
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, _NESTED):
            stack.extend(ast.iter_child_nodes(node))


@per_tree
def _md_scopes(tree: ast.AST) -> Iterator[tuple[list[ast.Assert], object]]:
    """`(asserts, is_md)` for the module and for each function: `is_md(node)` says whether
    `node` is a value read from a `.md` path there (a parameter shadows the module's name)."""
    defs = (n for n in walk_once(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
    context = module_reads_context(tree)
    module_env = context[0]
    for scope in (tree, *defs):
        own = bound_names(scope)
        args = getattr(scope, "args", None)
        params = {a.arg for a in ast.walk(args) if isinstance(a, ast.arg)} if args else set()
        hidden = params - own.keys()
        reads = md_reads(scope, tree, context) - hidden
        env = {k: v for k, v in module_env.items() if k not in hidden} | own
        yield ([n for n in _own_nodes(scope) if isinstance(n, ast.Assert)],
               lambda node, reads=reads, env=env: is_md_read(node, reads, env))


def _compare_pairs(test: ast.AST, ops: tuple) -> Iterator[tuple[ast.AST, ast.AST, ast.cmpop]]:
    """Each adjacent operand pair of every comparison in `test` using one of `ops`."""
    for cmp in (n for n in ast.walk(test) if isinstance(n, ast.Compare)):
        operands = [cmp.left, *cmp.comparators]
        for op, a, b in zip(cmp.ops, operands, operands[1:]):
            if isinstance(op, ops):
                yield a, b, op


def _int_constant(node: ast.AST) -> bool:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        node = node.operand
    return isinstance(node, ast.Constant) and type(node.value) is int


def _with_int(test: ast.AST, is_subject) -> bool:
    """Does an ordering or equality comparison in `test` pair an int constant with a
    subject (either way round)?"""
    return any((is_subject(a) and _int_constant(b)) or (is_subject(b) and _int_constant(a))
               for a, b, _ in _compare_pairs(test, _COMPARES))


# --- md-read-assert ----------------------------------------------------------------------

def _is_re_call(func: ast.AST) -> bool:
    """`re.search` and friends, or the same method of a `re.compile(...)` pattern."""
    return (isinstance(func, ast.Attribute) and func.attr in _RE_CALLS
            and (dotted(func.value) == "re" or (isinstance(func.value, ast.Call)
                                                and dotted(func.value.func) == "re.compile")))


def _asserts_on_prose(test: ast.AST, is_md) -> bool:
    """`in`/`not in`, an `re` search or `startswith`/`endswith` applied to a `.md` read."""
    for a, b, _ in _compare_pairs(test, (ast.In, ast.NotIn)):
        if is_md(a) or is_md(b):
            return True
    for call in (n for n in ast.walk(test) if isinstance(n, ast.Call)):
        if _is_re_call(call.func) and any(is_md(arg) for arg in call.args):
            return True
        if (isinstance(call.func, ast.Attribute) and call.func.attr in _PREFIX_CALLS
                and is_md(call.func.value)):
            return True
    return False


def md_read_assert(tree: ast.AST) -> Iterator[Finding]:
    """An assert that searches or prefix-matches raw text read from a `.md` path."""
    for asserts, is_md in _md_scopes(tree):
        for node in asserts:
            if _asserts_on_prose(node.test, is_md):
                yield Finding("md-read-assert", node.lineno, node.end_lineno)


# --- line-literal --------------------------------------------------------------------------

def _line_named(node: ast.AST) -> bool:
    """`x.lineno`, `x["line"]`, `x.get("line")`, an element of one, or `int(...)` of one."""
    if isinstance(node, ast.Attribute):
        return node.attr in _LINE_NAMES
    if isinstance(node, ast.Subscript):
        key = node.slice
        return (isinstance(key, ast.Constant) and key.value in _LINE_NAMES) or _line_named(node.value)
    if not isinstance(node, ast.Call):
        return False
    if dotted(node.func) == "int" and len(node.args) == 1:
        return _line_named(node.args[0])
    first = node.args[0] if node.args else None
    return (isinstance(node.func, ast.Attribute) and node.func.attr == "get"
            and isinstance(first, ast.Constant) and first.value in _LINE_NAMES)


def line_literal(tree: ast.AST) -> Iterator[Finding]:
    """An assert comparing an int constant with a line number."""
    for node in (n for n in walk_once(tree) if isinstance(n, ast.Assert)):
        if _with_int(node.test, _line_named):
            yield Finding("line-literal", node.lineno, node.end_lineno)


# --- doc-line-cap --------------------------------------------------------------------------

def _md_line_total(node: ast.AST, is_md) -> bool:
    """`len(<md read>.splitlines())` or `<md read>.count("\\n")`."""
    if isinstance(node, ast.Call) and dotted(node.func) == "len" and len(node.args) == 1:
        node = node.args[0]
        return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "splitlines" and is_md(node.func.value))
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "count" and len(node.args) == 1
            and isinstance(node.args[0], ast.Constant) and node.args[0].value == "\n"
            and is_md(node.func.value))


def doc_line_cap(tree: ast.AST) -> Iterator[Finding]:
    """An assert comparing a `.md` read's line total with an int constant."""
    for asserts, is_md in _md_scopes(tree):
        for node in asserts:
            if _with_int(node.test, lambda n: _md_line_total(n, is_md)):
                yield Finding("doc-line-cap", node.lineno, node.end_lineno)


# --- prose-regex ---------------------------------------------------------------------------

_RE_FUNCS = frozenset({"search", "match", "fullmatch", "findall", "finditer", "sub", "subn",
                       "split", "compile"})
_PLAN_PARSERS = frozenset({"plan_tasks", "extract_tasks"})


def _calls(tree: ast.AST) -> list[ast.Call]:
    return [n for n in walk_once(tree) if isinstance(n, ast.Call)]


def _captures_console(call: ast.Call) -> bool:
    name = dotted(call.func)
    if name in ("subprocess.check_output", "check_output"):
        return True
    return name == "subprocess.run" and any(
        kw.arg == "capture_output" and isinstance(kw.value, ast.Constant)
        and kw.value.value is True for kw in call.keywords)


def _reads_prose(tree: ast.AST, calls: list[ast.Call]) -> bool:
    """Does the module read a `.md` path, parse plan fields or capture console output?"""
    env: dict = {}
    for scope in (tree, *(n for n in walk_once(tree)
                          if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))):
        env.update(bound_names(scope))
    reads = md_reads(tree, tree)
    return any((dotted(c.func) or "").split(".")[-1] in _PLAN_PARSERS or _captures_console(c)
               or is_md_read(c, reads, env) for c in calls)


def prose_regex(tree: ast.AST) -> Iterator[Finding]:
    """An `re.*` call in a module that also works from prose (a `.md` read, parsed plan
    fields or captured console output)."""
    calls = _calls(tree)
    if not _reads_prose(tree, calls):
        return
    for call in calls:
        name = dotted(call.func) or ""
        if name.startswith("re.") and name[3:] in _RE_FUNCS:
            yield Finding("prose-regex", call.lineno, call.end_lineno)


# --- wall-clock ----------------------------------------------------------------------------

_CLOCKS = frozenset({"time.time", "time.monotonic", "time.perf_counter", "time.time_ns",
                     "time.monotonic_ns", "time.perf_counter_ns", "monotonic",
                     "perf_counter"})


def _clocky(node: ast.AST, names: set[str]) -> bool:
    """Does `node` call a wall clock or use a name bound from one?"""
    return any((isinstance(n, ast.Call) and dotted(n.func) in _CLOCKS)
               or (isinstance(n, ast.Name) and n.id in names) for n in ast.walk(node))


def _elapsed(node: ast.AST, clock_names: set[str], diff_names: set[str]) -> bool:
    """A clock difference, or a name bound to one."""
    if isinstance(node, ast.Name):
        return node.id in diff_names
    return (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub)
            and _clocky(node, clock_names))


def _number(node: ast.AST) -> bool:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        node = node.operand
    return isinstance(node, ast.Constant) and type(node.value) in (int, float)


def wall_clock(tree: ast.AST) -> Iterator[Finding]:
    """`time.sleep`, or an assert comparing a clock difference with a number."""
    clock_names: set[str] = set()
    diff_names: set[str] = set()
    for node in walk_once(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = {t.id for t in targets if isinstance(t, ast.Name)}
            if _elapsed(node.value, clock_names, diff_names):
                diff_names |= names
            elif _clocky(node.value, clock_names):
                clock_names |= names
    for node in walk_once(tree):
        if isinstance(node, ast.Call) and dotted(node.func) in ("time.sleep", "sleep"):
            yield Finding("wall-clock", node.lineno, node.end_lineno)
        elif isinstance(node, ast.Assert) and any(
                (_elapsed(a, clock_names, diff_names) and _number(b))
                or (_elapsed(b, clock_names, diff_names) and _number(a))
                for a, b, _ in _compare_pairs(node.test, _COMPARES)):
            yield Finding("wall-clock", node.lineno, node.end_lineno)


VISITORS = {"md-read-assert": md_read_assert, "line-literal": line_literal,
            "doc-line-cap": doc_line_cap, "prose-regex": prose_regex,
            "wall-clock": wall_clock}


def repo_gating(root) -> list[str]:
    """The gating set for the repo at `root`: `fragility.gating_rules` of its config through
    `fragility_registry.gating_set` (raises `ConfigError` on an unknown id)."""
    from repo_config_load import load_repo_config
    return gating_set(load_repo_config(root).config)



def visit(tree: ast.AST, path: str, ctx=None) -> list[Finding]:
    """The flag findings for one module at `path`, one per rule per line, by line."""
    on_test_file = is_test_file(path)
    found = {(hit.line, hit.rule_id): hit
             for rule in RULES
             if rule.family == "flag" and rule.id in VISITORS and (rule.side == "test") == on_test_file
             for hit in VISITORS[rule.id](tree)}
    return [found[key] for key in sorted(found)]
