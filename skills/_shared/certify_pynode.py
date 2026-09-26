"""certify_pynode — is a junit testcase the guard file's own test definition? [R6]

design: audit-pass-does-not-bind (detailed-design-certifier.md §2 [R6], sub-note (h),
PR #162 alias ruling 2026-09-25).

A pytest junit report spells node `path::A::B::name[param]` as classname
`<path's module>.A.B`, name `name[param]`, and (xunit1) `file` / `line`: where the test
function is *defined* (pytest's `item.location`: the unwrapped function's file and its
code's first line, 0-based; a decorated function's first line is its first decorator).
The dotted classname does not encode the node chain: a module `tests/t/test_x.py`
collected beside `tests/t.py` spells `tests.t.test_x` too, and a function it imports from
`tests/t.py` reports `file=tests/t.py`. So a case's classes and name are trusted only when
the guard file's own text says they are one test definition, at the line the case reports.

`defines(source, classes, name, line)` is True only when, in the guard file's text
(`source`, parsed with `ast`, never imported):
  * `classes[0]` is a class statement at the module's top level (the last one so named),
    and each later class is a class statement in the body of the one before it or of an
    in-file base class of it (the C3 order of its bases that are `Name` / `Attribute`
    references to classes of this file; other bases, e.g. `unittest.TestCase` or an
    imported class, are opaque and add nothing);
  * `name` is a `def` / `async def` statement at the module's top level when `classes`
    is empty, else in the body of the innermost class or of its in-file bases, the first
    in that C3 order that has one (the method Python's attribute lookup finds);
  * `line` (0-based) is that statement's first line: its first decorator's, else its `def`.
Anything else is False: a name that is not a class in the chain (so a function guard has
no cases under it but its own `[param]` ids), a test built by assignment, inside an `if`
or `try`, or inherited from another file, a wrapper without `functools.wraps`, a report
without `line`, or a guard file that does not parse. Each fails closed: never the guard's.

`source` is the guard file's text: `python_source` decodes its bytes strictly in the codec
Python picks for a source file (a UTF-8 BOM or a PEP 263 coding cookie, else UTF-8), so
the `ast` parse and the xunit1 `line` refer to the same text. A guard the strict decode
rejects is `guard-undecodable` (fail closed), which includes some files CPython accepts:
see known issue L92.

Residual: only a function object whose code starts on the same line as the declared
`def` passes for it (the line is the finest coordinate xunit1 reports), e.g. a lambda in
the `def` line's default or decorator, aliased into a collected module by committed code:
deliberately built code, the committed-code class of protocol §KNOWN BYPASS list.
"""

from __future__ import annotations

import ast
import io
import tokenize
from functools import lru_cache

FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)


def python_source(data: bytes) -> str | None:
    """`data` decoded strictly (`tokenize.open`): a UTF-8 BOM or a PEP 263 coding cookie
    picks the codec (else UTF-8), the BOM is dropped, newlines are universal. None when the
    strict decode rejects it (an unknown codec, a BOM with another cookie, any byte invalid
    in the codec, a codec whose decoder raises); such a guard is `guard-undecodable` and
    defines nothing (fail closed). Stricter than CPython, which also compiles, e.g., a
    non-UTF-8 byte in a comment: known issue L92."""
    try:
        encoding, _lines = tokenize.detect_encoding(io.BytesIO(data).readline)
        with io.TextIOWrapper(io.BytesIO(data), encoding, line_buffering=True) as text:
            return text.read()
    except (SyntaxError, UnicodeError, LookupError):  # UnicodeError: punycode, undefined, ...
        return None


@lru_cache(maxsize=16)
def _module(source: str) -> ast.Module | None:
    try:
        return ast.parse(source)
    except (SyntaxError, ValueError):
        return None


def _last(body, name: str, kinds):
    found = None
    for stmt in body:
        if isinstance(stmt, kinds) and stmt.name == name:
            found = stmt
    return found


class _File:
    def __init__(self, module: ast.Module):
        self.module = module
        self.resolving: set[int] = set()

    def base(self, expr):
        """The in-file class a base expression names, or None (opaque)."""
        if isinstance(expr, ast.Name):
            return _last(self.module.body, expr.id, ast.ClassDef)
        if isinstance(expr, ast.Attribute):
            outer = self.base(expr.value)
            return self.member(outer, expr.attr, ast.ClassDef) if outer else None
        return None

    def mro(self, cls: ast.ClassDef) -> list[ast.ClassDef] | None:
        """C3 order of `cls` over its in-file bases; None on a cycle or no order."""
        if id(cls) in self.resolving:
            return None
        self.resolving.add(id(cls))
        try:
            bases = [b for b in (self.base(e) for e in cls.bases) if b is not None]
            seqs = [self.mro(b) for b in bases]
            if any(s is None for s in seqs):
                return None
            return _c3([cls], [list(s) for s in seqs] + [list(bases)])
        finally:
            self.resolving.discard(id(cls))

    def member(self, cls: ast.ClassDef, name: str, kinds):
        order = self.mro(cls)
        for owner in order or ():
            found = _last(owner.body, name, kinds)
            if found is not None:
                return found
        return None


def _c3(head: list, seqs: list[list]) -> list | None:
    out = list(head)
    seqs = [s for s in seqs if s]
    while seqs:
        for seq in seqs:
            candidate = seq[0]
            if not any(candidate in s[1:] for s in seqs):
                break
        else:
            return None
        out.append(candidate)
        seqs = [s[1:] if s[0] is candidate else s for s in seqs]
        seqs = [s for s in seqs if s]
    return out


def _first_line(node) -> int:
    return min([node.lineno, *(d.lineno for d in node.decorator_list)]) - 1


def defines(source: str | None, classes: list[str], name: str, line: int | None) -> bool:
    """True when the guard file's text defines test `classes::name` at `line` (module
    docstring)."""
    module = _module(source) if source is not None else None
    if module is None or line is None:
        return False
    f = _File(module)
    scope = None
    for cls_name in classes:
        scope = (_last(module.body, cls_name, ast.ClassDef) if scope is None
                 else f.member(scope, cls_name, ast.ClassDef))
        if scope is None:
            return False
    test = _last(module.body, name, FUNCS) if scope is None else f.member(scope, name, FUNCS)
    return test is not None and _first_line(test) == line
