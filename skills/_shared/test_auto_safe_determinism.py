"""Determinism audit (OQ1) for the shared AUTO-SAFE resolver.

The carry's soundness proof (RME condition 5, Phase 2) depends on the resolver being a PURE
function: the same (base, ours, theirs) inputs must produce byte-identical output every time it
runs -- on the producer's machine now, and on the verifier's machine (possibly much) later. This
pins that property directly (repeated runs, byte-identical) for a keep-both class and the row
merge, and
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


# ---- source scan: no time/env/random imports anywhere in the resolver ------------------
# `conflict_parse.py` joined the list in round 11, when the region scanner was split out of
# `classify.py`. The scan must name every module the resolve path executes, or splitting a file
# becomes a way to smuggle nondeterminism past this audit. Round 17 added `resolvers.py` (the
# per-class merges, split out of `resolve.py`) and `resolve_totality.py`, which the resolve path has
# executed since round 12 without being listed. `auto_safe_resolution.py` is deliberately NOT
# listed: it draws the per-call marker-label nonce from `secrets`, which reaches marker lines only,
# and `test_the_nonce_never_reaches_resolved_output_and_resolved_bytes_are_stable` pins that.
# `shaped_merge.py` joined with the `shaped-line-merge` class (basesync-three-way-verifier), and
# `decisions_union.py` with the design-dir `decisions.md` lane the shared byte path takes before diff3.

def test_resolve_and_classify_have_no_time_env_random_imports():
    for name in ("resolve.py", "resolvers.py", "resolve_totality.py", "classify.py",
                 "conflict_parse.py", "shaped_merge.py", "decisions_union.py"):
        path = os.path.join(_MERGE_SCRIPTS, name)
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src, filename=name)
        forbidden = _imported_module_names(tree) & _FORBIDDEN_MODULES
        assert not forbidden, f"{name} imports forbidden nondeterministic module(s): {forbidden}"
        assert not _uses_environ_or_getenv(tree), f"{name} reads the process environment"


# ---- repeated-run byte-identity: a keep-both class and the row merge ------------------
# Round 20: this used to pin `id-renumber-collision`, which is now GATED (`classify.GATED`) and
# defers; a deferral's text carries the per-call marker nonce, so it is not byte-stable by design.

def test_log_entry_insertion_is_deterministic_across_repeated_runs():
    base = "## History\n\n- **2026-01-01** — base entry\n"
    ours = "## History\n\n- **2026-01-04** — ours entry\n  ours body\n- **2026-01-01** — base entry\n"
    theirs = ("## History\n\n- **2026-01-03** — theirs a\n- **2026-01-02** — theirs b\n"
              "- **2026-01-01** — base entry\n")
    results = {resolve_conflict_bytes(base=base, ours=ours, theirs=theirs) for _ in range(5)}
    assert len(results) == 1, results
    status, _merged = next(iter(results))
    assert status == RESOLVED


def test_design_inventory_row_merge_is_deterministic_across_repeated_runs():
    # Round 17 (F3): the row merge decides each row against base, so D12 is a base row theirs
    # edited; two DIFFERENT new D12 rows over an empty base now (correctly) defer.
    head = "| Design | Name | Status |\n| --- | --- | --- |\n"
    base = head + "| D12 | a | x |\n"
    ours = base + "| D15 | c | design |\n"
    theirs = head + "| D12 | a | THEIRS |\n| D14 | b | design |\n"
    results = {resolve_conflict_bytes(base=base, ours=ours, theirs=theirs) for _ in range(5)}
    assert len(results) == 1, results
    status, _merged = next(iter(results))
    assert status == RESOLVED
