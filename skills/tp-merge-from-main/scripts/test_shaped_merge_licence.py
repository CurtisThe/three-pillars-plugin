"""`resolve_totality.required_counts` for `shaped-line-merge`: the first BASE-AWARE licence.

Spec: basesync-three-way-verifier detailed-design.md (Interfaces: `resolve_totality.required_counts`)
and plan Task 4.3. For this label the count a key must keep is
`(C(ours) & C(theirs) & C(base)) + ((C(ours) - C(base)) | (C(theirs) - C(base)))`, so a BASE line a
side changed or removed is let go. That is licensed only while the base line is shaped (an ID row, a
slug row or a log bullet, never a delimiter row); any other let-go base line keeps its exact
`ours + theirs` multiplicity, so `unplaceable` reports it. The function runs outside the resolver's
`try`, so it never raises. Every other label is held to the counts it had before: shown by a
differential against a local copy of the old rule over `conflict_fixtures.ALL_FIXTURES`, not a
snapshot. Rule: skills/_shared/test-fragility.md (behaviour only; inputs are built by the parser).
"""
import os
import sys
from collections import Counter

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import classify  # noqa: E402
from classify import MECHANICAL, SEMANTIC, Hunk, classify_file  # noqa: E402
from conflict_fixtures import ALL_FIXTURES, diff3  # noqa: E402
from resolve_totality import (  # noqa: E402
    CROSS_SIDE_DEDUPE, key_for, licensed_keys, overproduced, required_counts, unplaceable,
)

LABEL = "shaped-line-merge"

R = "| `ci-settle` | wait for the status context | Seed |"
R2 = "| `ci-settle` | wait for the status context | Done |"
X = "| `new-ours` | the ours row | Seed |"
Y = "| `new-theirs` | the theirs row | Seed |"
D1 = "| D1 | design-a | Seed |"
SEED = "- **2026-07-01** — the seed entry."
SEED2 = "- **2026-07-02** — the second seed entry."
OURS = "- **2026-07-03** — the ours entry."
THEIRS = "- **2026-07-04** — the theirs entry."
NAMED = "- **`design-a`** — Implemented (2026-07-04)."
PROSE = "some prose a mechanical merge does not understand"
DELIM = "|--------|------|--------|"
SPACED_DELIM = "| --- | --- | --- |"
HEADER = "| Design | Note | Status |"


def hunk(ours, base, theirs):
    """The first conflict region of the diff3 text built from the three sides."""
    parsed = classify.parse_conflict(diff3("\n".join(ours), "\n".join(base), "\n".join(theirs)))
    return next(seg for seg in parsed.segments if isinstance(seg, Hunk))


def counts(h, label=LABEL):
    """`required_counts` under the label's own key, with zero entries dropped."""
    return +required_counts(h, key_for(label), label)


def licence(h):
    """The design's formula, transcribed straight from the spec."""
    o, b, t = Counter(h.ours), Counter(h.base), Counter(h.theirs)
    return +((o & t & b) + ((o - b) | (t - b)))


# Hunks whose every line is shaped, so the whole formula applies.
SHAPED = {
    "the #219 slug-row shape": hunk([R, X], [R], [R2, Y]),
    "the #188 History two-line rewrite": hunk([OURS, SEED2], [SEED, SEED2], [SEED, THEIRS]),
    "slug rows beside an ID row": hunk([D1, R, X], [D1, R], [D1, R2, Y]),
    "name-keyed bullets": hunk([NAMED, OURS], [NAMED], [NAMED, THEIRS]),
    "both sides insert the same line": hunk([R, X], [R], [R, X]),
    "a line a side repeats": hunk([R, X, X], [R], [R2, X]),
    "one side removes a base line": hunk([SEED], [SEED, SEED2], [SEED, SEED2, THEIRS]),
}


@pytest.mark.parametrize("name", SHAPED)
def test_a_shaped_hunk_keeps_the_base_aware_formula_count(name):
    assert counts(SHAPED[name]) == licence(SHAPED[name])


def test_the_219_hunk_lets_go_only_the_row_a_side_changed():
    required = counts(SHAPED["the #219 slug-row shape"])
    assert required == Counter({R2: 1, Y: 1, X: 1}), "R was edited by theirs: base line let go"


def test_the_history_rewrite_lets_go_both_seed_lines():
    required = counts(SHAPED["the #188 History two-line rewrite"])
    assert required == Counter({OURS: 1, THEIRS: 1})


def test_the_licence_is_strictly_below_the_exact_count_it_replaces():
    h = SHAPED["the #219 slug-row shape"]
    exact = Counter(h.ours) + Counter(h.theirs)
    assert exact[R] == 1 and counts(h)[R] == 0


# --- a let-go base line that is not shaped keeps its exact multiplicity -------------------------

UNSHAPED = {"prose": PROSE, "a separator row": DELIM, "a spaced separator row": SPACED_DELIM,
            "a header row": HEADER, "a blank line": ""}


@pytest.mark.parametrize("name", UNSHAPED)
def test_an_unshaped_base_line_a_side_removed_keeps_exact_multiplicity(name):
    line = UNSHAPED[name]
    h = hunk([R, X], [R, line], [R2, line])        # ours removed `line`, theirs kept it
    exact = Counter(h.ours) + Counter(h.theirs)
    assert exact[line] == 1
    assert counts(h)[line] == 1                    # not 0: the licence does not reach it
    assert counts(h)[R] == 0                       # the shaped base line is still let go


@pytest.mark.parametrize("name", UNSHAPED)
def test_unplaceable_reports_the_unshaped_line_a_merge_dropped(name):
    line = UNSHAPED[name]
    h = hunk([R, X], [R, line], [R2, line])
    dropped = [R2, X]                              # the merge dropped `line`
    assert unplaceable(h, LABEL, dropped) == [line]
    assert unplaceable(h, LABEL, dropped + [line]) == []


def test_a_shaped_base_line_a_side_removed_is_not_reported():
    h = hunk([R, X], [R], [R2, Y])
    assert unplaceable(h, LABEL, [R2, Y, X]) == []


def test_a_line_a_side_added_is_reported_when_the_merge_drops_it():
    h = hunk([R, X], [R], [R2, Y])
    assert unplaceable(h, LABEL, [R2, Y]) == [X]
    assert unplaceable(h, LABEL, [R2, X]) == [Y]


def test_a_history_merge_missing_a_side_s_new_line_is_reported():
    h = SHAPED["the #188 History two-line rewrite"]
    assert unplaceable(h, LABEL, [OURS, THEIRS]) == []
    assert unplaceable(h, LABEL, [OURS]) == [THEIRS]


# --- it never raises ----------------------------------------------------------------------------

ODD = ["", "\r", "|", "| |", "|\t", "| `", "- **", " ", "<<<", PROSE * 40]


@pytest.mark.parametrize("line", ODD, ids=[repr(s[:12]) for s in ODD])
def test_required_counts_never_raises_on_an_odd_base_line(line):
    h = hunk([R, X], [R, line], [R2, line])
    exact = Counter(h.ours) + Counter(h.theirs)
    assert counts(h)[line] == exact[line]


def test_the_empty_base_hunk_has_no_base_line_to_let_go():
    h = classify.parse_conflict(
        "<<<<<<< ours\n" + X + "\n||||||| base\n=======\n" + Y + "\n>>>>>>> theirs").segments[0]
    assert counts(h) == Counter({X: 1, Y: 1})


# --- overproduced is unchanged ------------------------------------------------------------------

def test_overproduced_still_bounds_the_output_by_every_input_line_base_included():
    h = SHAPED["the #219 slug-row shape"]
    assert overproduced(h, LABEL, [R2, Y, X]) == []
    assert overproduced(h, LABEL, [R, R2, Y, X]) == []          # re-emitting base is not invention
    invented = "| `invented` | a row no side wrote | Seed |"
    assert overproduced(h, LABEL, [R2, Y, X, invented]) == [invented]


# --- every other label: the counts it had before ------------------------------------------------

def old_required(h, key, label):
    """The pre-4.3 rule, copied here as the reference: exact `ours + theirs`, or `max` on the keys a
    cross-side-dedupe class's licence covers."""
    ours, theirs = (Counter(key(line) for line in side) for side in (h.ours, h.theirs))
    if label not in CROSS_SIDE_DEDUPE:
        return ours + theirs
    covered = licensed_keys(h, key, label)
    return Counter({k: (max(ours[k], theirs[k]) if covered is None or k in covered
                        else ours[k] + theirs[k]) for k in set(ours) | set(theirs)})


def fixture_hunks():
    return [(name, seg) for name, text in ALL_FIXTURES
            for seg in classify_file(text).segments if isinstance(seg, Hunk)]


def test_every_other_label_returns_its_old_counts_on_the_fixture_corpus():
    labels = sorted((MECHANICAL | SEMANTIC) - {LABEL})
    population = fixture_hunks() + list(SHAPED.items())
    assert len(population) >= 10 and len(labels) >= 8, "the differential must not be vacuous"
    moved = []
    for name, h in population:
        for label in labels:
            key = key_for(label)
            if required_counts(h, key, label) != old_required(h, key, label):
                moved.append((name, label))
    assert not moved, moved[:6]
