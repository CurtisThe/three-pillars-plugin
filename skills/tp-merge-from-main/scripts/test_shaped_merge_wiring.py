"""`shaped-line-merge` wired end to end: classify -> confidence gate -> resolver -> totality -> verify.

Spec: basesync-three-way-verifier detailed-design.md (Interfaces: the import graph; Test strategy:
Wiring) and plan Task 4.5. A shaped-line hunk resolves behind `classify.is_confident`, the
`resolve_totality` post-conditions and the zero-drop verifier; a refusal defers only its own hunk;
the import graph is acyclic whichever module loads first (shown by re-execution, one fresh
interpreter per module). Inputs are three-stage texts or diff3 text parsed by the resolver's own
parser. Rule: skills/_shared/test-fragility.md (behaviour only; counterfactuals are monkeypatched at
the module attribute the resolver calls).
"""
import dataclasses
import os
import subprocess
import sys

import pytest

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.join(SCRIPTS, "..", "..", "_shared"))
import shaped_merge  # noqa: E402
import verify  # noqa: E402
from auto_safe_resolution import diff3_conflict, resolve_conflict_bytes  # noqa: E402
from classify import (  # noqa: E402
    AUTO_RESOLVE, GATED, MECHANICAL, Hunk, classify_file, classify_hunk, is_confident,
)
from conflict_fixtures import diff3  # noqa: E402
from resolve import DEFER, DEFER_CODES, RESOLVED, resolve_file, resolve_hunk  # noqa: E402
from resolve_totality import unplaceable  # noqa: E402

LABEL = "shaped-line-merge"
HEAD = "| Slug | Note | Status |\n| --- | --- | --- |\n"
R = "| `ci-settle-statuscontext` | settle the status context | Planned |"
R2 = R.replace("Planned", "Done")
R3 = R.replace("Planned", "Blocked")
X = "| `ours-new` | the ours row | Planned |"
Y = "| `theirs-new` | the theirs row | Planned |"
D1, D2 = "| D1 | design-a | Seed |", "| D2 | design-b | Seed |"
DELIM = "|--------|------|--------|"
SEED = "- **2026-07-01** — the seed entry."
SEED2 = "- **2026-07-02** — the second seed entry."
OURS = "- **2026-07-03** — the ours entry."
THEIRS = "- **2026-07-04** — the theirs entry."
PROSE = "some prose a mechanical merge does not understand"

# The three stages of the #219 shape: theirs moved `R` on to `R2`, each side appended a row.
BASE = HEAD + R + "\n"
OURS_TEXT = HEAD + R + "\n" + X + "\n"
THEIRS_TEXT = HEAD + R2 + "\n" + Y + "\n"


def regions(text):
    return [seg for seg in classify_file(text).segments if isinstance(seg, Hunk)]


def shaped_hunk():
    """The classified #219 region, built the way the byte path builds it (`git merge-file`)."""
    d = diff3_conflict(base=BASE, ours=OURS_TEXT, theirs=THEIRS_TEXT)
    (h,) = regions(d.text)
    return h


# --- end to end: resolve_conflict_bytes -> label -> verify ---------------------------------------

def test_the_219_shape_resolves_to_theirs_row_then_theirs_new_then_ours_new():
    status, merged = resolve_conflict_bytes(base=BASE, ours=OURS_TEXT, theirs=THEIRS_TEXT)
    assert status == RESOLVED
    assert merged == HEAD + "\n".join([R2, Y, X]) + "\n"


def test_the_resolution_is_labelled_shaped_line_merge_hunk_by_hunk():
    d = diff3_conflict(base=BASE, ours=OURS_TEXT, theirs=THEIRS_TEXT)
    status, _lines, results = resolve_file(d.text, labels=d.labels)
    assert status == RESOLVED
    assert [(r.label, r.status, r.code) for r in results] == [(LABEL, RESOLVED, "")]


def test_the_verifier_passes_the_resolution_against_the_base():
    _status, merged = resolve_conflict_bytes(base=BASE, ours=OURS_TEXT, theirs=THEIRS_TEXT)
    got = verify.verify(OURS_TEXT, THEIRS_TEXT, merged, base=BASE, mechanical_applied=True)
    assert got.verdict == verify.VERIFIED, got.dropped


def test_the_verifier_reports_a_resolution_that_lost_a_row_a_side_added():
    lossy = HEAD + "\n".join([R2, Y]) + "\n"                   # ours' new row is gone
    got = verify.verify(OURS_TEXT, THEIRS_TEXT, lossy, base=BASE, mechanical_applied=True)
    assert got.verdict == verify.DROPS_DETECTED


# --- the label's place in the class sets --------------------------------------------------------

def test_the_label_is_mechanical_and_auto_resolvable_and_not_gated():
    assert LABEL in MECHANICAL and LABEL in AUTO_RESOLVE and LABEL not in GATED


# --- the confidence gate fails closed -------------------------------------------------------------

def test_the_classified_219_hunk_is_confident():
    h = shaped_hunk()
    assert h.label == LABEL and is_confident(h) is True


@pytest.mark.parametrize("side", ["ours", "theirs", "base"])
def test_a_shaped_hunk_mutated_with_a_prose_line_is_not_confident(side):
    h = shaped_hunk()
    mutated = dataclasses.replace(h, **{side: [*getattr(h, side), PROSE]})
    assert mutated.label == LABEL
    assert is_confident(mutated) is False


def test_a_mutated_hunk_defers_as_not_confident_and_round_trips():
    h = shaped_hunk()
    mutated = dataclasses.replace(h, ours=[*h.ours, PROSE])
    r = resolve_hunk(mutated)
    assert (r.status, r.code) == (DEFER, "not-confident")
    assert PROSE in r.lines


# --- the post-conditions backstop the resolver ---------------------------------------------------

def test_a_resolver_that_drops_a_line_a_side_added_is_caught_by_unplaceable(monkeypatch):
    h = shaped_hunk()
    monkeypatch.setattr(shaped_merge, "merge_shaped_lines", lambda _h: [R2, Y])   # X is gone
    assert unplaceable(h, LABEL, [R2, Y]) == [X]
    r = resolve_hunk(h)
    assert (r.status, r.code) == (DEFER, "would-drop")


def test_an_unshaped_let_go_base_line_is_would_drop_and_never_a_raise(monkeypatch):
    """The base holds a delimiter row `resolve_totality` does not call shaped, so the licence cannot
    let it go: a merge that drops it is `would-drop`. The gate and the merge are forced open here,
    because the real ones refuse such a hunk first."""
    h = Hunk(ours=[R, X], base=[R, DELIM], theirs=[R2, DELIM], label=LABEL, post_context="")
    monkeypatch.setattr(shaped_merge, "is_shaped_line_merge", lambda _h: True)
    monkeypatch.setattr(shaped_merge, "merge_shaped_lines", lambda _h: [R2, X])    # DELIM is gone
    assert unplaceable(h, LABEL, [R2, X]) == [DELIM]
    r = resolve_hunk(h)
    assert (r.status, r.code) == (DEFER, "would-drop")
    assert DELIM in r.lines


# --- a refusal defers only its own hunk ----------------------------------------------------------

def test_a_refused_shape_is_a_cannot_place_deferral_of_that_hunk_only():
    refused = diff3(R2, R, R3, pre=HEAD.rstrip("\n"))              # both sides changed R, differently
    fine = diff3(R + "\n" + X, R, R2 + "\n" + Y)
    text = refused + "\nsome clean prose between the regions\n" + fine
    status, lines, results = resolve_file(text)
    assert status == DEFER
    assert [(r.label, r.status, r.code) for r in results] == [
        (LABEL, DEFER, "cannot-place"), (LABEL, RESOLVED, "")]
    assert "both sides changed" in results[0].reason
    assert "<<<<<<< ours" in lines and R3 in lines                 # the refused region is verbatim
    assert [R2, Y, X] == lines[-3:]                                # the other region merged


def test_the_refusal_type_never_reaches_the_caller_as_a_raise():
    (h,) = regions(diff3(R2, R, R3, pre=HEAD.rstrip("\n")))
    assert h.label == LABEL
    with pytest.raises(shaped_merge.ShapedMergeRefused):
        shaped_merge.merge_shaped_lines(h)
    assert resolve_hunk(h).code in DEFER_CODES                     # resolve_hunk turns it into a code


# --- the log arm: a continuation line after the region keeps it out of the class -----------------

def test_a_log_hunk_ending_at_the_file_end_is_shaped_and_resolves():
    text = diff3(OURS + "\n" + SEED2, SEED + "\n" + SEED2, SEED + "\n" + THEIRS)
    (h,) = regions(text)
    assert h.label == LABEL
    status, lines, _results = resolve_file(text)
    assert status == RESOLVED and lines == [OURS, THEIRS]


def test_the_task_4_1_continuation_hunk_is_not_shaped_and_is_deferred():
    """`Workaround: rerun.` continues an entry above the region, so theirs' last line would move to
    another entry: `append-only-log` refuses it, and so does the shaped class."""
    text = diff3(SEED + "\n" + OURS, SEED, SEED + "\n" + THEIRS) + "\nWorkaround: rerun.\n"
    (h,) = regions(text)
    assert classify_hunk(h) != LABEL and h.label == "generic-prose"
    r = resolve_hunk(h)
    assert (r.status, r.code) == (DEFER, "semantic")


# --- an ID-only table hunk keeps the label and the fallthrough it has today ---------------------

def test_an_id_only_table_hunk_the_inventory_class_takes_keeps_its_label():
    (h,) = regions(diff3(D1 + "\n" + D2, D1, D1.replace("Seed", "Done")))
    assert h.label == "design-inventory-row-merge"


def test_an_id_only_table_hunk_the_inventory_class_refuses_stays_generic_prose():
    """A blank line inside ours ends the table, which `table_run_refusal` refuses; the shaped class
    refuses an ID-only hunk too, so nothing claims it and it defers to a human."""
    (h,) = regions(diff3(D1 + "\n\n" + D2, D1, D1.replace("Seed", "Done")))
    assert h.label == "generic-prose"
    assert resolve_hunk(h).code == "semantic"


# --- the import graph is acyclic whichever module loads first ----------------------------------

@pytest.mark.parametrize("module", ["keyed_classes", "resolve_totality", "merge_driver"])
def test_each_module_imports_first_in_a_fresh_interpreter(module):
    done = subprocess.run([sys.executable, "-c", f"import {module}"], cwd=SCRIPTS,
                          capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr[-400:]
