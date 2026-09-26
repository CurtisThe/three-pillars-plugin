"""test_task_targets.py — the plan **Targets** grammar (operator rulings on #165, C3).

design: local-implement-and-review

Behaviour only: what a field runs, that order never changes it, that a whole-file item
covers its nodes, and that every malformed or missing field is not runnable (never an
oracle). Pure: no git, no filesystem.
"""
from __future__ import annotations

import itertools

import pytest

import task_scope
import task_targets

A = "pkg/test_a.py"
B = "pkg/sub/test_b.py"


def _specs(field):
    return task_targets.parse_targets(field)["specs"]


@pytest.mark.parametrize("field,specs,kind", [
    (f"`{A}::test_x`", [f"{A}::test_x"], "pytest-node"),
    (f"`{A}::TestK::test_y`", [f"{A}::TestK::test_y"], "pytest-node"),
    (f"`{A}`", [A], "pytest-file"),
    (f"`{A}::test_x`, `{B}`", sorted([f"{A}::test_x", B]), "pytest-file"),
    (f"`{A}::test_x`,`{A}::test_y`", [f"{A}::test_x", f"{A}::test_y"], "pytest-node"),
    ("`test_root.py` (new)", ["test_root.py"], "pytest-file"),
])
def test_valid_fields_run_exactly_their_items(field, specs, kind):
    got = task_targets.parse_targets(field)
    assert (got["specs"], got["kind"], got["canonical"], got["errors"]) == (
        specs, kind, True, [])


def test_order_never_matters():
    items = [f"`{A}::test_x`", f"`{B}::test_z`", f"`{A}::test_y`"]
    results = {tuple(_specs(", ".join(p))) for p in itertools.permutations(items)}
    assert len(results) == 1


def test_whole_file_item_covers_its_nodes_in_any_order():
    for field in (f"`{A}`, `{A}::test_x`", f"`{A}::test_x`, `{A}`"):
        assert _specs(field) == [A]


def test_new_marker_is_recorded_per_file():
    got = task_targets.parse_targets(f"`{A}::test_x` (new), `{A}::test_y` (new), `{B}`")
    assert got["new_files"] == [A] and got["files"] == sorted([A, B])


@pytest.mark.parametrize("field", [
    "",                                   # present but empty
    f"{A}::test_x",                       # not backticked
    f"`{A}::test_x`;`{B}`",               # wrong separator
    f"`{A}::test_x`,",                    # trailing comma
    f"`{A}::test_x` extra words",         # prose after an item
    "`pkg/test_a.txt`",                   # not a .py path
    "`/abs/test_a.py`",                   # absolute
    "`pkg/../test_a.py`",                 # parent segment
    "`./test_a.py`",                      # dot segment
    f"`{A}::test_*`",                     # glob node
    f"`{A}::test_x[1]`",                  # parametrize id
    f"`{A} test_x`",                      # space-separated node
    f"`{A}::test_x`, `{A}::test_x`",      # duplicate
    f"`{A}::test_x` (new), `{A}::test_y`",  # marker on some items of one file
    f"`{A}` (created)",                   # unknown marker
    "None",                               # `none` is lower-case only
])
def test_malformed_fields_are_not_runnable(field):
    got = task_targets.parse_targets(field)
    assert got["errors"] and got["reason"] == task_targets.MALFORMED
    assert (got["kind"], got["canonical"], got["specs"]) == ("not-runnable", False, [])


def test_missing_is_non_canonical_and_none_is_canonical():
    missing = task_targets.parse_targets(None)
    assert (missing["kind"], missing["canonical"], missing["reason"]) == (
        "not-runnable", False, task_targets.MISSING)
    declared = task_targets.parse_targets("  none ")
    assert (declared["kind"], declared["canonical"], declared["specs"]) == (
        "not-runnable", True, [])


def test_validate_agrees_with_parse():
    for field in (None, "none", f"`{A}`", f"`{A}", "x"):
        assert bool(task_targets.validate(field)) == (
            task_targets.parse_targets(field)["reason"] == task_targets.MALFORMED)


def test_task_scope_reexports_the_one_parser():
    assert task_scope.parse_targets is task_targets.parse_targets
