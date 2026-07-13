"""Determinism audit (OQ1) for the shared AUTO-SAFE resolver.

The carry's soundness proof (RME condition 5, Phase 2) depends on the resolver being a PURE
function: the same (base, ours, theirs) inputs must produce byte-identical output every time it
runs -- on the producer's machine now, and on the verifier's machine (possibly much) later. This
pins that property directly (repeated runs, byte-identical) for BOTH AUTO-SAFE classes, and
source-scans resolve.py/classify.py for the only imports that could sneak in nondeterminism
(time, environment, randomness).
"""
from __future__ import annotations

import ast
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from auto_safe_resolution import RESOLVED, resolve_conflict_bytes  # noqa: E402

_MERGE_SCRIPTS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "tp-merge-from-main", "scripts")
)

_FORBIDDEN_MODULES = {"time", "random"}


def _imported_module_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".")[0])
    return names


def _uses_environ_or_getenv(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv"):
            return True
        if isinstance(node, ast.Name) and node.id == "environ":
            return True
    return False


# ---- source scan: no time/env/random imports in resolve.py / classify.py --------------

def test_resolve_and_classify_have_no_time_env_random_imports():
    for name in ("resolve.py", "classify.py"):
        path = os.path.join(_MERGE_SCRIPTS, name)
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src, filename=name)
        forbidden = _imported_module_names(tree) & _FORBIDDEN_MODULES
        assert not forbidden, f"{name} imports forbidden nondeterministic module(s): {forbidden}"
        assert not _uses_environ_or_getenv(tree), f"{name} reads the process environment"


# ---- repeated-run byte-identity: both AUTO-SAFE classes --------------------------------

def test_id_renumber_collision_is_deterministic_across_repeated_runs():
    base = "### L1: base entry\nbase body\n"
    ours = base + "### L4: ours unique\nours body\n"
    theirs = base + "### L4: theirs a\ntheirs body a\n### L5: theirs b\ntheirs body b\n"
    results = {resolve_conflict_bytes(base=base, ours=ours, theirs=theirs) for _ in range(5)}
    assert len(results) == 1, results
    status, _merged = next(iter(results))
    assert status == RESOLVED


def test_design_inventory_row_merge_is_deterministic_across_repeated_runs():
    base = "| Design | Name | Status |\n| --- | --- | --- |\n"
    ours = base + "| D12 | a | OURS |\n| D15 | c | design |\n"
    theirs = base + "| D12 | a | THEIRS |\n| D14 | b | design |\n"
    results = {resolve_conflict_bytes(base=base, ours=ours, theirs=theirs) for _ in range(5)}
    assert len(results) == 1, results
    status, _merged = next(iter(results))
    assert status == RESOLVED
