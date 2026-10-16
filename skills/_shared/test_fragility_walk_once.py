"""The lint's per-module work is done once per module, not once per function or rule.

design: fragile-test-prevention (impl-audit follow-up). A module with many functions
used to be re-walked (`bound_names`, `_returning_helpers`) once per function, so the
invariant-47 scan went quadratic. These tests count the walks (a behaviour of the
code, never a wall-clock) and pin that the findings are the same as ever.
"""
from __future__ import annotations

import ast

import fragility_ast
import fragility_repo_rules
from fragility_ast import bound_names, md_reads, per_tree, walk_once
from fragility_rules_flag import md_read_assert

N_FUNCS = 40


def _module(n: int = N_FUNCS) -> ast.Module:
    helper = "def doc():\n    return open('x.md').read()\n"
    funcs = "".join(
        f"def test_{i}():\n    text = doc()\n    assert 'word{i}' in text\n" for i in range(n))
    return ast.parse(f"import re\n{helper}{funcs}")


def test_md_read_assert_computes_the_module_helpers_once(monkeypatch):
    real, calls = fragility_ast._returning_helpers, []
    monkeypatch.setattr(fragility_ast, "_returning_helpers", lambda m: calls.append(m) or real(m))
    hits = list(md_read_assert(_module()))
    assert len(hits) == N_FUNCS
    assert len(calls) == 1


def test_md_reads_with_a_shared_context_matches_the_one_off_call():
    tree = _module(3)
    context = fragility_ast.module_reads_context(tree)
    for fn in tree.body[2:]:
        assert md_reads(fn, tree, context) == md_reads(fn, tree) == {"doc", "text"}


def test_bound_names_walks_each_scope_once(monkeypatch):
    tree = _module(3)
    real, walked = fragility_ast._bound_names, []
    monkeypatch.setattr(fragility_ast, "_bound_names", lambda s: walked.append(s) or real(s))
    first = bound_names(tree)
    assert bound_names(tree) is first and walked == [tree]


def test_per_tree_recomputes_for_a_new_tree_and_keeps_the_whole_result():
    seen = []

    @per_tree
    def collect(tree):
        seen.append(tree)
        return iter([1, 2])

    a, b = ast.parse("x = 1"), ast.parse("x = 1")
    assert collect(a) == collect(a) == [1, 2]
    assert collect(b) == [1, 2]
    assert seen == [a, b]


def test_walk_once_is_ast_walk_in_the_same_order():
    tree = _module(3)
    assert walk_once(tree) == list(ast.walk(tree))


def test_forbidden_read_asserts_walks_the_module_functions_once_for_many_rows(monkeypatch):
    src = ("import re\n\ndef doc():\n    return open('a/x.md').read()\n\n"
           "def test_a():\n    assert 'w' in doc()\n")
    tree = ast.parse(src)
    real, calls = fragility_repo_rules.bound_names, []
    monkeypatch.setattr(fragility_repo_rules, "bound_names", lambda s: calls.append(s) or real(s))
    hits = [list(fragility_repo_rules._forbidden_read_asserts(tree, g)) for g in ("*.md", "a/*.md", "*.txt")]
    assert [len(h) for h in hits] == [1, 1, 0]
    assert len(calls) == 1 + 2  # the module once, plus each of its two functions once
