"""`shaped_merge.merge_shaped_lines`: the keyed line-wise merge of one shaped conflict hunk.

Spec: basesync-three-way-verifier detailed-design.md (Interfaces: `merge_shaped_lines`, the per-line
table) and plan Task 4.2. Each side is aligned to base by key (a row's ID or slug; a log bullet's
bold lead when unique, else the whole line). A line one side changed or removed while the other is
byte-equal takes that change, every insertion is kept (theirs' run, then ours', at each anchor) and
every ambiguous shape raises `ShapedMergeRefused`. Inputs are small hand-built diff3 hunks; every
case is a concrete example with its exact expected lines. Rule: skills/_shared/test-fragility.md
(behaviour only: the self-check is shown by patching the assembly step, not by reading source).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import classify  # noqa: E402
import resolve_totality  # noqa: E402
import shaped_merge  # noqa: E402
from conflict_fixtures import diff3, diff3_empty_base  # noqa: E402
from shaped_merge import ShapedMergeRefused, merge_shaped_lines  # noqa: E402

R = "| `ci-settle` | wait for the status context | Seed |"
R2 = "| `ci-settle` | wait for the status context | Done |"
R3 = "| `ci-settle` | wait for the status context | Parked |"
X = "| `new-ours` | the ours row | Seed |"
Y = "| `new-theirs` | the theirs row | Seed |"
Z = "| `new-shared` | a row both sides add | Seed |"
Z2 = "| `new-shared` | the same slug, other text | Seed |"
D1 = "| D1 | design-a | Seed |"
D2 = "| D2 | design-b | Seed |"
D2_DONE = "| D2 | design-b | Done |"

SEED = "- **2026-07-01** — the seed entry."
SEED_BY_OURS = "- **2026-07-01** — the seed entry, reworded by ours."
SEED2 = "- **2026-07-02** — the second seed entry."
SEED2_BY_THEIRS = "- **2026-07-02** — the second seed entry, reworded by theirs."
OURS = "- **2026-07-03** — the ours entry."
THEIRS = "- **2026-07-04** — the theirs entry."
SAME_DAY_A = "- **2026-07-05** — first thing that day."
SAME_DAY_B = "- **2026-07-05** — second thing that day."
SAME_DAY_A_EDITED = "- **2026-07-05** — first thing that day, edited."
SAME_DAY_B2 = "- **2026-07-05** — second thing that day, corrected."
LATER = "- **2026-07-06** — a later ours entry."


def hunk(ours, base, theirs):
    """The first conflict region of the diff3 text built from the three sides, parsed the way the
    resolver parses it."""
    block = diff3("\n".join(ours), "\n".join(base), "\n".join(theirs))
    return next(seg for seg in classify.parse_conflict(block).segments
                if isinstance(seg, classify.Hunk))


def refusal(region):
    """The exception `merge_shaped_lines` raises for `region` (the test fails if it returns)."""
    with pytest.raises(ShapedMergeRefused) as caught:
        merge_shaped_lines(region)
    assert type(caught.value) is ShapedMergeRefused
    assert not isinstance(caught.value, resolve_totality.CannotPlace)
    return caught.value


# --- the per-line table: one row of the DD table per case -----------------------------------------

MERGED = {
    "kept by both sides: the base line":
        ([R, D1], [R, D1], [R, D1], [R, D1]),
    "kept by both while another line changes: the base line":
        ([R, D2_DONE], [R, D2], [R, D2], [R, D2_DONE]),
    "ours changed it, theirs byte-equal: ours' change":
        ([R2, D1], [R, D1], [R, D1], [R2, D1]),
    "theirs changed it, ours byte-equal: theirs' change":
        ([R, D1], [R, D1], [R2, D1], [R2, D1]),
    "ours removed it, theirs byte-equal: removed":
        ([D1], [R, D1], [R, D1], [D1]),
    "theirs removed it, ours byte-equal: removed":
        ([R, D1], [R, D1], [D1], [D1]),
    "both changed it to identical bytes: once":
        ([R2, D1], [R, D1], [R2, D1], [R2, D1]),
    "both removed it: nothing":
        ([D1], [R, D1], [D1], [D1]),
    "an ID row changes like a slug row":
        ([D1, D2_DONE], [D1, D2], [D1, D2], [D1, D2_DONE]),
}


@pytest.mark.parametrize("name", MERGED)
def test_each_row_of_the_per_line_table(name):
    ours, base, theirs, expected = MERGED[name]
    assert merge_shaped_lines(hunk(ours, base, theirs)) == expected


def test_the_219_shape_puts_theirs_insertion_before_ours():
    """base [R], ours [R, X], theirs [R', Y]: theirs' edit, then Y (theirs), then X (ours)."""
    assert merge_shaped_lines(hunk([R, X], [R], [R2, Y])) == [R2, Y, X]


def test_merging_returns_a_plain_list_of_the_lines():
    out = merge_shaped_lines(hunk([R, X], [R], [R2, Y]))
    assert type(out) is list and all(type(line) is str for line in out)


# --- insertions: anchored after the nearest preceding matched line --------------------------------

def test_an_insertion_between_two_matched_lines_stays_between_them():
    assert merge_shaped_lines(hunk([R, X, D1], [R, D1], [R, D1])) == [R, X, D1]


def test_an_insertion_at_the_top_anchors_at_minus_one():
    assert merge_shaped_lines(hunk([X, R], [R], [R2])) == [X, R2]


def test_top_insertions_from_both_sides_put_theirs_first():
    assert merge_shaped_lines(hunk([X, R], [R], [Y, R])) == [Y, X, R]


def test_insertions_after_the_same_line_put_theirs_run_first_then_ours():
    got = merge_shaped_lines(hunk([R, X, D1], [R, D1], [R, Y, Z, D1]))
    assert got == [R, Y, Z, X, D1]


def test_an_identical_insertion_on_both_sides_is_emitted_once():
    assert merge_shaped_lines(hunk([R, Z], [R], [R2, Z])) == [R2, Z]


def test_an_identical_insertion_run_on_both_sides_is_emitted_once():
    assert merge_shaped_lines(hunk([R, X, Y], [R], [R2, X, Y])) == [R2, X, Y]


def test_an_identical_run_at_the_top_is_emitted_once():
    assert merge_shaped_lines(hunk([X, R], [R], [X, R2])) == [X, R2]


def test_an_insertion_after_a_line_the_other_side_removed_is_kept():
    assert merge_shaped_lines(hunk([R, D1, X], [R, D1], [R])) == [R, X]


# --- the log arm: bold lead when unique, the whole line otherwise ---------------------------------

def test_the_188_history_rewrite_with_unique_leads_resolves():
    """Each side reworded a different History line (the lead keeps its identity): both changes."""
    got = merge_shaped_lines(hunk([SEED_BY_OURS, SEED2], [SEED, SEED2], [SEED, SEED2_BY_THEIRS]))
    assert got == [SEED_BY_OURS, SEED2_BY_THEIRS]


def test_a_history_rewrite_that_replaces_each_lines_lead_keeps_both_new_lines():
    got = merge_shaped_lines(hunk([OURS, SEED2], [SEED, SEED2], [SEED, THEIRS]))
    assert got == [OURS, THEIRS]


def test_a_lead_unique_in_base_and_side_aligns_by_the_lead():
    """Ours' reworded line shares base's lead, so it is base's entry changed, not a new line."""
    assert merge_shaped_lines(hunk([SEED_BY_OURS], [SEED], [SEED])) == [SEED_BY_OURS]


def test_a_repeated_lead_aligns_by_the_whole_line():
    """Base has two lines with one date lead, so the lead is no key: theirs' corrected line is a
    new line after the first, base's old one is removed, and ours' untouched copy goes with it."""
    got = merge_shaped_lines(hunk([SAME_DAY_A, SAME_DAY_B, LATER], [SAME_DAY_A, SAME_DAY_B],
                                  [SAME_DAY_A, SAME_DAY_B2]))
    assert got == [SAME_DAY_A, SAME_DAY_B2, LATER]


def test_a_lead_repeated_in_one_side_only_aligns_that_side_by_the_whole_line():
    """The lead is unique in base, but ours now holds it twice: ours aligns by whole line (its
    copy of A matches base's A, B is an insertion) and theirs, with a unique lead, aligns by it."""
    got = merge_shaped_lines(hunk([SAME_DAY_A, SAME_DAY_B], [SAME_DAY_A], [SAME_DAY_A_EDITED]))
    assert got == [SAME_DAY_A_EDITED, SAME_DAY_B]


def test_a_name_keyed_bullet_aligns_by_its_slug_lead():
    base = "- **`design-a`** — Implemented (2026-07-04)."
    edited = "- **`design-a`** — Implemented (2026-07-05)."
    assert merge_shaped_lines(hunk([base], [base], [edited])) == [edited]


# --- refused: ambiguous shapes --------------------------------------------------------------------

AMBIGUOUS = {
    "both changed it, differently": hunk([R2], [R], [R3]),
    "ours edited it, theirs removed it": hunk([R2, D1], [R, D1], [D1]),
    "ours removed it, theirs edited it": hunk([D1], [R, D1], [R2, D1]),
    "both changed one log bullet differently":
        hunk([SEED_BY_OURS, SEED2], [SEED, SEED2], [SEED + " More.", SEED2]),
    "ours reordered the matched lines": hunk([D1, R], [R, D1], [R, D1]),
    "theirs reordered the matched lines": hunk([R, D1, D2], [R, D1, D2], [D2, R, D1]),
    "ours reordered log bullets": hunk([SEED2, SEED], [SEED, SEED2], [SEED, SEED2]),
    "a duplicate row key in ours": hunk([R, R2], [R], [R]),
    "a duplicate row key in theirs": hunk([R], [R], [D1, D1]),
    "a duplicate row key in base": hunk([R], [R, R2], [R]),
    "a duplicate ID row key": hunk([D1, D1], [D1], [D1]),
    "a duplicate whole log line": hunk([SEED, SEED], [SEED], [SEED]),
    "two different rows added under one slug": hunk([R, Z], [R], [R, Z2]),
}


@pytest.mark.parametrize("name", AMBIGUOUS)
def test_an_ambiguous_shape_raises_shaped_merge_refused(name):
    refusal(AMBIGUOUS[name])


# --- refused: a shape fault (checked before any merging) ------------------------------------------

SHAPE_FAULTS = {
    "a prose line": hunk([R, "Some prose, not a row."], [R], [R2]),
    "a prose line in theirs": hunk([R], [R], [R2, "Workaround: rerun the job."]),
    "a prose line in base": hunk([R], [R, "A note."], [R]),
    "a blank line": hunk([R, "", X], [R], [R2]),
    "a delimiter row": hunk([R, "|--------|------|--------|"], [R], [R2]),
    "a header row": hunk([R, X], ["| Design | Note | Status |", R], [R2]),
    "a wrapped bullet": hunk([SEED, OURS, "  and it continues"], [SEED], [SEED]),
    "a plain list item": hunk([SEED, "- plain list item"], [SEED], [SEED]),
    "a carriage return inside a row": hunk([R, "| `x` | a\rb | Seed |"], [R], [R2]),
}


@pytest.mark.parametrize("name", SHAPE_FAULTS)
def test_a_shape_fault_raises_shaped_merge_refused(name):
    refusal(SHAPE_FAULTS[name])


def test_a_two_way_region_raises_shaped_merge_refused():
    two_way = "<<<<<<< ours\n" + R + "\n=======\n" + R2 + "\n>>>>>>> theirs"
    region = next(seg for seg in classify.parse_conflict(two_way).segments
                  if isinstance(seg, classify.Hunk))
    refusal(region)


def test_an_empty_base_raises_shaped_merge_refused():
    region = classify.parse_conflict(diff3_empty_base(X, Y)).segments[0]
    refusal(region)


# --- the self-check: every line the sides added must be in the output -----------------------------

def test_an_assembly_that_drops_a_non_base_line_is_caught(monkeypatch):
    real = shaped_merge._assemble

    def drops_ours_row(*args, **kwargs):
        return [line for line in real(*args, **kwargs) if line != X]

    monkeypatch.setattr(shaped_merge, "_assemble", drops_ours_row)
    refusal(hunk([R, X], [R], [R2, Y]))


def test_an_assembly_that_drops_a_changed_line_is_caught(monkeypatch):
    real = shaped_merge._assemble
    monkeypatch.setattr(shaped_merge, "_assemble",
                        lambda *a, **k: [line for line in real(*a, **k) if line != R2])
    refusal(hunk([R, X], [R], [R2, Y]))


# --- the self-check: no line is written more often than any side has it --------------------------

def test_a_bullet_both_sides_add_beside_more_theirs_lines_is_never_written_twice():
    # PR #224 r1: both sides add OURS; theirs also adds THEIRS at the same anchor, so the two
    # insertion runs differ and `_assemble` used to emit [OURS, THEIRS, OURS].
    refusal(hunk([SEED_BY_OURS, OURS], [SEED], [SEED, OURS, THEIRS]))


def test_an_assembly_that_writes_a_line_twice_is_caught(monkeypatch):
    real = shaped_merge._assemble
    monkeypatch.setattr(shaped_merge, "_assemble", lambda *a, **k: real(*a, **k) + [Y])
    refusal(hunk([R, X], [R], [R2, Y]))
