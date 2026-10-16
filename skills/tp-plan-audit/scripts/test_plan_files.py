"""test_plan_files.py — the **File** field is backticked repo-relative paths.

design: consumer-repo-parity (H4, Phase 3)

The declared File grammar mirrors the Targets grammar (``task_targets._split``/
``_item_errors``) with two relaxations: **any** repo-relative path is legal (not
only ``.py``), and ``::`` is not part of the item (a path is a path, not a node).
``(new)`` / ``(modify)`` are per item and optional — an item with neither is still
canonical and means "touches" (marker ``None``). ``none`` is canonical and empty.
Anything else is non-canonical and carries at least one error.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from plan_files import parse_file_field  # noqa: E402


# --- canonical forms ------------------------------------------------------

def test_none_is_canonical_with_no_items():
    r = parse_file_field("none")
    assert r["canonical"] is True
    assert r["items"] == []
    assert r["errors"] == []


def test_items_carry_path_and_marker():
    r = parse_file_field("`a.py` (new), `b/c.md` (modify), `d.txt`")
    assert r["canonical"] is True
    assert r["errors"] == []
    assert [i["path"] for i in r["items"]] == ["a.py", "b/c.md", "d.txt"]
    assert [i["marker"] for i in r["items"]] == ["new", "modify", None]


@pytest.mark.parametrize("path", [
    ".python-version",
    ".nvmrc",
    "Makefile",
    ".three-pillars/config.json",
], ids=["python-version", "nvmrc", "Makefile", "dotdir-path"])
def test_legal_paths(path):
    r = parse_file_field(f"`{path}` (new)")
    assert r["canonical"] is True, r["errors"]
    assert r["items"] == [{"path": path, "marker": "new"}]


def test_unmarked_item_is_canonical_marker_none():
    r = parse_file_field("`skills/_shared/x.py`")
    assert r["canonical"] is True, r["errors"]
    assert r["items"] == [{"path": "skills/_shared/x.py", "marker": None}]


def test_deep_nested_path():
    r = parse_file_field("`a/b/c/d/e.md` (modify)")
    assert r["canonical"] is True, r["errors"]
    assert r["items"] == [{"path": "a/b/c/d/e.md", "marker": "modify"}]


# --- non-canonical forms: each carries an error ---------------------------

@pytest.mark.parametrize("field", [
    "`a.py::test_x`",        # a `::` item (paths have no nodes)
    "`/abs/path.py`",        # a leading /
    "`a/../b.py`",           # a .. segment
    "`./a.py`",              # a . segment
    "`a.py (new)",           # an unbalanced backtick (no close)
    "`a.py` (new), b.md (modify)",  # free prose (second item not backticked)
], ids=["colon-colon", "leading-slash", "dotdot-segment",
        "dot-segment", "unbalanced-backtick", "free-prose"])
def test_non_canonical_forms_carry_an_error(field):
    r = parse_file_field(field)
    assert r["canonical"] is False
    assert r["errors"], "expected at least one error for a non-canonical field"
