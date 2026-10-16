"""fragility_rules_gating.py — the gating fragility rules.

design: fragile-test-prevention (detailed-design-lint §Rule registry)

`golden-hash` and `shape-pin` (test side), `deny-literal` (production side): AST
shapes over one parsed module, built on `fragility_ast`. `visit(tree, path, ctx)`
runs the gating-family rules of `fragility_registry.RULES` whose side matches `path`
and returns `Finding(rule_id, line, end_line)` sorted by line (the flagged node's
own span); a rule of side `any` runs on both file kinds (`name-kill`, from
`fragility_rules_name_kill`); the caller applies waivers and the gating set, and `ctx` is unused here.
Names trace through bindings in the same scope and at module level (a parameter
shadows an outer binding); a name that cannot be traced is never flagged.
"""
from __future__ import annotations

import ast
from typing import Iterator, NamedTuple

from fragility_ast import bound_names, dotted, is_test_file, per_tree, walk_once
from fragility_registry import RULES
from fragility_rules_name_kill import name_kill

# Matched on name tokens, so severity names such as `BLOCKING` are not filters.
FILTER_NAME_TOKENS = ("DENY", "DENYLIST", "BLOCK", "BLOCKED", "BLOCKLIST", "REJECT",
                      "REJECTED")

_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_MAX_HOPS = 8
_OPENERS = frozenset({"open", "io.open"})
_PATH_CTORS = frozenset({"Path", "pathlib.Path", "PurePath", "pathlib.PurePath"})
_PATH_STEPS = frozenset({"resolve", "absolute", "expanduser", "open"})
_SOURCE_CALLS = frozenset({"inspect.getsource", "inspect.getsourcelines"})
_AST_CALLS = frozenset({"ast.parse", "ast.dump"})
_SOURCE_WRAPPERS = frozenset({"textwrap.dedent", "str"})


class Finding(NamedTuple):
    rule_id: str
    line: int
    end_line: int


def _aliases(tree: ast.AST) -> dict[str, str]:
    """Local name -> dotted origin for every import in the module (any scope)."""
    aliases: dict[str, str] = {}
    for node in walk_once(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                root = item.name.split(".")[0]
                aliases[item.asname or root] = item.name if item.asname else root
        elif isinstance(node, ast.ImportFrom):
            for item in node.names:
                origin = f"{node.module}.{item.name}" if node.module else item.name
                aliases[item.asname or item.name] = origin
    return aliases


class _Env:
    """One scope's bindings and the module's import aliases."""

    def __init__(self, env: dict, aliases: dict):
        self.env, self.aliases = env, aliases

    def canon(self, node: ast.AST) -> str | None:
        """The dotted name of `node`, its head replaced by its import origin."""
        name = dotted(node)
        if name is None:
            return None
        head, _, rest = name.partition(".")
        origin = self.aliases.get(head, head)
        return f"{origin}.{rest}" if rest else origin

    def _via(self, node: ast.Name, hops: int, fn, default=None):
        """`fn` of the binding of Name `node` (one hop deeper), else `default`."""
        value = self.env.get(node.id)
        return default if value is None or hops >= _MAX_HOPS else fn(value, hops + 1)

    def open_path(self, node: ast.AST, hops: int = 0) -> ast.AST | None:
        """The path of an opened file (`open(p)`), else None."""
        if isinstance(node, ast.Name):
            return self._via(node, hops, self.open_path)
        if isinstance(node, ast.Call) and self.canon(node.func) in _OPENERS and node.args:
            return node.args[0]
        return None

    def read_path(self, node: ast.AST, hops: int = 0) -> ast.AST | None:
        """The path a file read (`read_text`, `read_bytes`, `open(p).read()`) reads, seen
        through names and method chains; None if `node` is not a read."""
        if isinstance(node, ast.Name):
            return self._via(node, hops, self.read_path)
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            return None
        if node.func.attr in ("read_text", "read_bytes"):
            return node.func.value
        if node.func.attr in ("read", "readlines"):
            return self.open_path(node.func.value)
        return self.read_path(node.func.value, hops)

    def py_path(self, node: ast.AST, hops: int = 0) -> bool:
        """A `.py` path: a constant, `<mod>.__file__`, or a join or step ending in one."""
        if isinstance(node, ast.Constant):
            return isinstance(node.value, str) and node.value.endswith(".py")
        if isinstance(node, ast.Attribute):
            return node.attr == "__file__"
        if isinstance(node, ast.Name):
            return self._via(node, hops, self.py_path, False)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            return self.py_path(node.right, hops)
        if not isinstance(node, ast.Call):
            return False
        name = self.canon(node.func)
        if name in _PATH_CTORS or name in _OPENERS:
            return bool(node.args) and self.py_path(node.args[0], hops)
        return (isinstance(node.func, ast.Attribute) and node.func.attr in _PATH_STEPS
                and self.py_path(node.func.value, hops))

    def _hashes_a_read(self, hasher: ast.AST, hops: int) -> bool:
        if isinstance(hasher, ast.Name):
            return self._via(hasher, hops, self._hashes_a_read, False)
        name = self.canon(hasher.func) if isinstance(hasher, ast.Call) else None
        return (name or "").startswith("hashlib.") and any(
            self.read_path(arg) is not None for arg in hasher.args)

    def digest_of_read(self, node: ast.AST, hops: int = 0) -> bool:
        """A `hashlib` `.hexdigest()`/`.digest()` of a file read, through names."""
        if isinstance(node, ast.Name):
            return self._via(node, hops, self.digest_of_read, False)
        return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("hexdigest", "digest")
                and self._hashes_a_read(node.func.value, hops))

    def pinned(self, node: ast.AST, hops: int = 0) -> bool:
        """Fixed outside the test: a constant, a name bound to one or imported, or an
        attribute of an imported module."""
        if isinstance(node, ast.Name):
            return self._via(node, hops, self.pinned, node.id in self.aliases)
        if isinstance(node, ast.Attribute):
            return (dotted(node) or ".").split(".")[0] in self.aliases
        return isinstance(node, ast.Constant)

    def source_trace(self, node: ast.AST, hops: int = 0) -> bool:
        """Does `node` trace to `getsource` or to a read of a `.py` path, through
        names, parses and method chains?"""
        if isinstance(node, ast.Name):
            return self._via(node, hops, self.source_trace, False)
        if not isinstance(node, ast.Call):
            return False
        name = self.canon(node.func)
        if name in _SOURCE_CALLS:
            return True
        if name in _AST_CALLS or name in _SOURCE_WRAPPERS:
            return any(self.source_trace(arg, hops) for arg in node.args)
        path = self.read_path(node)
        if path is not None:
            return self.py_path(path)
        return isinstance(node.func, ast.Attribute) and self.source_trace(node.func.value, hops)


@per_tree
def _scopes(tree: ast.AST) -> Iterator[tuple[list[ast.AST], _Env]]:
    """`(own nodes, resolver)` per module, def and class. A nested scope sees its
    parents' bindings minus its parameters (a class body's do not reach its methods)."""
    aliases = _aliases(tree)

    def walk(scope: ast.AST, outer: dict):
        nodes, nested, stack = [], [], list(scope.body)
        while stack:
            node = stack.pop()
            (nested if isinstance(node, _DEFS) else nodes).append(node)
            if not isinstance(node, _DEFS):
                stack.extend(ast.iter_child_nodes(node))
        args = getattr(scope, "args", None)
        params = {a.arg for a in ast.walk(args) if isinstance(a, ast.arg)} if args else set()
        env = {k: v for k, v in outer.items() if k not in params} | bound_names(scope)
        yield nodes, _Env(env, aliases)
        for child in nested:
            yield from walk(child, outer if isinstance(scope, ast.ClassDef) else env)

    yield from walk(tree, {})


def _eq_pairs(test: ast.AST) -> Iterator[tuple[ast.AST, ast.AST]]:
    """Each side of every `==` in `test`, paired both ways round."""
    for cmp in (n for n in ast.walk(test) if isinstance(n, ast.Compare)):
        operands = [cmp.left, *cmp.comparators]
        for op, a, b in zip(cmp.ops, operands, operands[1:]):
            if isinstance(op, ast.Eq):
                yield a, b
                yield b, a


def golden_hash(tree: ast.AST) -> Iterator[Finding]:
    """An equality assert of a digest of a file read against a value not computed in the test."""
    for nodes, env in _scopes(tree):
        for assertion in (n for n in nodes if isinstance(n, ast.Assert)):
            if any(env.digest_of_read(x) and env.pinned(y) for x, y in _eq_pairs(assertion.test)):
                yield Finding("golden-hash", assertion.lineno, assertion.end_lineno)


def shape_pin(tree: ast.AST) -> Iterator[Finding]:
    """Every `getsource` call, and `ast.parse`/`ast.dump` of a module's own source."""
    for nodes, env in _scopes(tree):
        for call in (n for n in nodes if isinstance(n, ast.Call)):
            name = env.canon(call.func)
            args = [*call.args, *(k.value for k in call.keywords)]
            if name in _SOURCE_CALLS or (
                    name in _AST_CALLS and any(env.source_trace(a) for a in args)):
                yield Finding("shape-pin", call.lineno, call.end_lineno)


def name_tokens(name: str) -> list[str]:
    """The upper-cased tokens of `name`, split on `_` and on lower-to-upper changes."""
    tokens, current = [], ""
    for ch in name:
        if ch == "_" or (ch.isupper() and current[-1:].islower()):
            tokens.append(current)
            current = "" if ch == "_" else ch
        else:
            current += ch
    return [token.upper() for token in [*tokens, current] if token]


def _collection_literal(node: ast.AST) -> bool:
    """A set/tuple/list literal with a constant element, or `set`/`frozenset`/`tuple` of one."""
    if isinstance(node, ast.Call):
        return (dotted(node.func) in ("set", "frozenset", "tuple") and len(node.args) == 1
                and not node.keywords and _collection_literal(node.args[0]))
    return (isinstance(node, (ast.Set, ast.Tuple, ast.List))
            and any(isinstance(elt, ast.Constant) for elt in node.elts))


def deny_literal(tree: ast.AST) -> Iterator[Finding]:
    """A filter-named binding to a hand-written literal collection."""
    for node in walk_once(tree):
        targets = (node.targets if isinstance(node, ast.Assign)
                   else [node.target] if isinstance(node, ast.AnnAssign) else [])
        if targets and _collection_literal(node.value) and any(
                isinstance(t, ast.Name) and set(name_tokens(t.id)) & set(FILTER_NAME_TOKENS)
                for t in targets):
            yield Finding("deny-literal", node.lineno, node.end_lineno)


VISITORS = {"golden-hash": golden_hash, "shape-pin": shape_pin, "deny-literal": deny_literal,
            "name-kill": name_kill}


def visit(tree: ast.AST, path: str, ctx=None) -> list[Finding]:
    """The gating findings for one module at `path`, one per rule per line, by line."""
    on_test_file = is_test_file(path)
    found = {(hit.line, hit.rule_id): hit
             for rule in RULES if rule.family == "gating"
             and rule.side in ("any", "test" if on_test_file else "production")
             for hit in VISITORS[rule.id](tree)}
    return [found[key] for key in sorted(found)]
