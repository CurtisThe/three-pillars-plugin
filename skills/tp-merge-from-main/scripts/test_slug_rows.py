"""Slug-keyed table rows: the `row` atom the zero-drop verifier gains for `` | `slug` | … | ``.

Spec: basesync-three-way-verifier detailed-design.md (the slug-row bullets) and plan Tasks 3.1-3.2. A
slug row's signature is its RAW backticked slug, so it can never collide with an ID row's
signature (`_norm` strips backticks from that one) and never needs an excuse (its signature is its
place key). Inputs are small hand-built tables; the corpus check is a differential A/B, not a
count pin. Rule: skills/_shared/test-fragility.md.
"""
import importlib.util
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "_shared"))
import classify  # noqa: E402
import resolve_totality  # noqa: E402
import verify_atoms  # noqa: E402
from conflict_fixtures import INVENTORY_ROW_MERGE, diff3  # noqa: E402
from task_scope import _git_env as clean_git_env  # noqa: E402  # shipped scrub; git_env is dev-only
from verify import DROPS_DETECTED, VERIFIED, verify  # noqa: E402
from verify_atoms import atoms  # noqa: E402
from verify_three_way import occurrences  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
HEADER = ["| Design | Note | Status |", "|--------|------|--------|"]


def doc(*lines):
    return "\n".join(lines) + "\n"


def row_atoms(text):
    return {sig for kind, sig in atoms(text) if kind == "row"}


# --- the atom: shape, raw backticks, disjoint from an ID row ---------------------------------

def test_a_slug_row_is_a_row_atom_keyed_by_its_raw_backticked_slug():
    assert ("row", "`ci-settle-statuscontext`") in atoms("| `ci-settle-statuscontext` | x | Done |")


def test_a_slug_row_tolerates_leading_space_and_a_digit_start():
    assert row_atoms("|   `2fa-gate` | x |") == {"`2fa-gate`"}


def test_a_slug_row_signature_differs_from_an_id_row_of_the_same_name():
    slug = row_atoms("| `ci-settle-statuscontext` | x | Done |")
    id_row = row_atoms("| D1 | ci-settle-statuscontext |")
    assert id_row == {"ci-settle-statuscontext"}
    assert slug == {"`ci-settle-statuscontext`"}
    assert slug.isdisjoint(id_row)


@pytest.mark.parametrize("line", [
    "| `Foo` | x |",             # uppercase slug
    "| `a b` | x |",             # a space is no slug character
    "| x `a-slug` | y |",        # the backtick is not the first thing in the cell
    "| plain | `a-slug` |",      # the slug is not in the first cell
    "| `-leading` | x |",        # a slug starts with [a-z0-9]
    "| `trailing | x |",         # unclosed backtick
], ids=["uppercase", "inner-space", "non-leading", "second-cell", "leading-dash", "unclosed"])
def test_a_first_cell_that_is_not_a_bare_slug_yields_no_slug_atom(line):
    assert row_atoms(line) == set()


def test_a_header_and_delimiter_row_stay_non_atoms_around_a_slug_row():
    assert row_atoms(doc(*HEADER, "| `alpha` | n | Seed |")) == {"`alpha`"}


# --- differential A/B over every tracked .md --------------------------------------------------

def tracked_markdown():
    run = subprocess.run(["git", "-C", str(ROOT), "ls-files", "*.md"], capture_output=True,
                         text=True, check=False, env=clean_git_env())
    if run.returncode != 0:
        pytest.skip("not a git checkout: no tracked markdown to measure")
    paths = [ROOT / p for p in run.stdout.splitlines() if (ROOT / p).is_file()]
    if not paths:
        pytest.skip("no tracked markdown files in this checkout")
    return paths


def test_enabling_the_slug_arm_only_adds_slug_row_atoms_on_every_tracked_markdown_file(monkeypatch):
    texts = [p.read_text(encoding="utf-8") for p in tracked_markdown()]
    enabled = [atoms(t) for t in texts]
    monkeypatch.setattr(verify_atoms, "SLUG_ROW", re.compile(r"(?!)"))
    disabled = [atoms(t) for t in texts]
    lost, changed, added = [], [], set()
    for off, on in zip(disabled, enabled):
        lost += [k for k in off if k not in on]
        changed += [k for k in off if k in on and off[k] != on[k]]
        added |= {k for k in on if k not in off}
    assert lost == [] and changed == []                     # 0 atoms lost, no signature moved
    assert all(kind == "row" and re.fullmatch(r"`[a-z0-9][a-z0-9-]*`", sig) for kind, sig in added)


# --- occurrences: place key and the multiset contract -----------------------------------------

SLUG_TABLE = doc(*HEADER, "| `alpha` | one | Seed |", "| D1 | alpha | x |", "| `beta` | two | Seed |",
                 "| `alpha` | one again | Seed |")


def test_a_slug_row_occurrence_has_the_raw_backticked_slug_as_its_place_key():
    slug_rows = [(o.sig, o.key, o.start, o.end) for o in occurrences(SLUG_TABLE) if o.sig[0] == "`"]
    assert slug_rows == [("`alpha`", "`alpha`", 2, 3), ("`beta`", "`beta`", 4, 5),
                         ("`alpha`", "`alpha`", 5, 6)]


def test_an_id_row_keeps_its_id_as_the_place_key_beside_slug_rows():
    assert [(o.sig, o.key) for o in occurrences(SLUG_TABLE) if o.sig == "alpha"] == [("alpha", "D1")]


def test_the_multiset_contract_holds_on_a_slug_row_table():
    counts = Counter((o.kind, o.sig) for o in occurrences(SLUG_TABLE))
    assert counts == Counter({("row", "`alpha`"): 2, ("row", "`beta`"): 1, ("row", "alpha"): 1})
    assert set(counts) == set(atoms(SLUG_TABLE))
    per_line = Counter(k for line in SLUG_TABLE.splitlines() for k in atoms(line))
    assert counts == per_line


# --- the three-way verdict: a slug row never needs an excuse ----------------------------------

BASE = doc(*HEADER, "| `ci-settle` | robustness | Seed |", "| `other` | n | Seed |")
EDITED = doc(*HEADER, "| `ci-settle` | robustness | Done |", "| `other` | n | Seed |")
RENAMED = doc(*HEADER, "| `ci-settle-v2` | robustness | Seed |", "| `other` | n | Seed |")


def three_way(ours, theirs, resolved):
    return verify(ours, theirs, resolved, base=BASE, mechanical_applied=True)


@pytest.mark.parametrize("changing_side", ["ours", "theirs"])
def test_a_one_side_edit_of_a_slug_rows_other_cells_verifies_with_nothing_excused(changing_side):
    ours, theirs = (EDITED, BASE) if changing_side == "ours" else (BASE, EDITED)
    result = three_way(ours, theirs, EDITED)
    assert (result.verdict, result.excused) == (VERIFIED, [])


@pytest.mark.parametrize("changing_side", ["ours", "theirs"])
def test_a_one_side_slug_rename_is_a_pure_removal_and_stays_a_drop(changing_side):
    ours, theirs = (RENAMED, BASE) if changing_side == "ours" else (BASE, RENAMED)
    result = three_way(ours, theirs, RENAMED)
    assert result.verdict == DROPS_DETECTED
    assert result.dropped == [("row", "`ci-settle`")] and result.excused == []


# --- classify and resolve_totality: a slug-row hunk leaves the inventory class ----------------

INVENTORY, FOCUS = "design-inventory-row-merge", "current-focus-reprioritization"
ID_LINE, SLUG_LINE = "| D12 | alpha | design | x |", "| `alpha-slug` | note | Seed |"


def hunks_of(text):
    return [s for s in classify.classify_file(text).segments if isinstance(s, classify.Hunk)]


@pytest.mark.parametrize("ours, theirs", [
    (f"{ID_LINE}\n{SLUG_LINE}", f"{ID_LINE}\n| D14 | b | design | y |"),    # the slug row is ours only
    (f"{ID_LINE}\n| D15 | c | design | x |", f"{ID_LINE}\n{SLUG_LINE}"),    # the slug row is theirs only
    (f"{ID_LINE}\n{SLUG_LINE}", f"{ID_LINE}\n| `beta-slug` | n | Seed |"),   # both sides carry one
], ids=["ours-only", "theirs-only", "both"])
def test_a_slug_row_hunk_is_never_an_inventory_row_merge(ours, theirs):
    (hunk,) = hunks_of(diff3(ours, ID_LINE, theirs))
    assert hunk.label not in (INVENTORY, FOCUS)


def test_a_slug_only_hunk_is_neither_inventory_nor_a_priority_reorder():
    text = diff3(f"{SLUG_LINE}\n| `beta` | x | Seed |", SLUG_LINE, "| `alpha-slug` | edited | Seed |",
                 pre="## Current Focus")
    (hunk,) = hunks_of(text)
    assert hunk.label not in (INVENTORY, FOCUS)


def test_id_only_table_hunks_classify_as_before():
    quoted = diff3(f"{ID_LINE}\n| D15 | c | design | x |", ID_LINE,
                   "| D12 | `alpha` | design | THEIRS |\n| D14 | b | design | y |")
    priority = diff3("| 3 | design | x |\n| 4 | other | y |", "| 3 | design | x |", "| 3 | design | z |")
    cases = {"fixture": (INVENTORY_ROW_MERGE, INVENTORY), "backticked-later-cell": (quoted, INVENTORY),
             "priority-table": (priority, FOCUS)}
    for name, (text, want) in cases.items():
        (hunk,) = hunks_of(text)
        assert hunk.label == want, name
        assert not any(classify.SLUG_ROW.match(line) for line in hunk.ours + hunk.theirs), name


MODULES = (verify_atoms, classify, resolve_totality)


def fresh_copy(module):
    """`module`'s file executed again under a throwaway name: its own top-level statements rerun."""
    spec = importlib.util.spec_from_file_location(module.__name__ + "_probe", module.__file__)
    copy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(copy)
    return copy


def test_each_module_owns_its_slug_regex(monkeypatch):
    for module in MODULES:
        assert isinstance(module.SLUG_ROW, re.Pattern), module.__name__
        assert module.SLUG_ROW.match("| `ci-settle` | x | Seed |").group(1) == "ci-settle"
        assert module.SLUG_ROW.match("| D12 | ci-settle | x |") is None
    own = {module: module.SLUG_ROW.pattern for module in MODULES}
    for module in MODULES:
        # Every OTHER module's regex becomes one that matches nothing; a module that took its
        # regex from another (by name or by attribute) would now carry that one, or lack its own.
        for other in MODULES:
            if other is not module:
                monkeypatch.setattr(other, "SLUG_ROW", re.compile(r"(?!)"))
        assert fresh_copy(module).SLUG_ROW.pattern == own[module], module.__name__
        monkeypatch.undo()
