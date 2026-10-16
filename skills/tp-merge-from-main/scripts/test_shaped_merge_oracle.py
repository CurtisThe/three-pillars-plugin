"""`licence_oracle.lost_lines` for `shaped-line-merge`: the test-side SECOND reading of the licence.

Spec: basesync-three-way-verifier detailed-design.md (Interfaces: `licence_oracle.lost_lines`) and
plan Task 4.4. `resolve_totality.required_counts` is the checker; this oracle is the answer key, and
it reaches the same count by another mechanism: the oracle's first read of `hunk.base`, the count
`(O & T & B) + ((O - B) | (T - B))` over RAW lines, with a let-go base line allowed only when the
oracle's own field-split predicates (`row_id_by_field`, `row_slug_by_field`, `is_log_entry_start`)
call it shaped. Any other base line keeps its exact `ours + theirs` multiplicity. Every other label
is held to the answer it had before: shown by a differential against a local copy of the old body
over `conflict_fixtures.ALL_FIXTURES`, not a snapshot. Rule: skills/_shared/test-fragility.md
(behaviour only; hunks are built by the parser, results are real `HunkResult`s).
"""
import os
import sys
from collections import Counter

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import classify  # noqa: E402
import licence_oracle as oracle  # noqa: E402
from classify import MECHANICAL, SEMANTIC, Hunk, classify_file  # noqa: E402
from conflict_fixtures import ALL_FIXTURES, diff3  # noqa: E402
from resolvers import HunkResult  # noqa: E402

LABEL = "shaped-line-merge"

R = "| `ci-settle` | wait for the status context | Seed |"
R2 = "| `ci-settle` | wait for the status context | Done |"
X = "| `new-ours` | the ours row | Seed |"
Y = "| `new-theirs` | the theirs row | Seed |"
D1 = "| D1 | design-a | Seed |"
D1_DONE = "| D1 | design-a | Done |"
SEED = "- **2026-07-01** — the seed entry."
SEED2 = "- **2026-07-02** — the second seed entry."
OURS = "- **2026-07-03** — the ours entry."
THEIRS = "- **2026-07-04** — the theirs entry."
NAMED = "- **`design-a`** — Implemented (2026-07-04)."
NAMED_DONE = "- **`design-a`** — Implemented (2026-07-05)."
PROSE = "some prose a mechanical merge does not understand"
DELIM = "|--------|------|--------|"
SPACED_DELIM = "| --- | --- | --- |"
HEADER = "| Design | Note | Status |"


def hunk(ours, base, theirs):
    """The first conflict region of the diff3 text built from the three sides."""
    parsed = classify.parse_conflict(diff3("\n".join(ours), "\n".join(base), "\n".join(theirs)))
    return next(seg for seg in parsed.segments if isinstance(seg, Hunk))


def lost(h, lines, label=LABEL):
    return oracle.lost_lines(h, HunkResult(label, "RESOLVED", list(lines)))


# --- the #219 hunk: ours kept R and added X; theirs edited R to R' and added Y -------------------

H219 = hunk([R, X], [R], [R2, Y])


def test_the_219_merge_loses_nothing():
    assert lost(H219, [R2, Y, X]) == []


def test_the_order_of_the_merged_lines_is_not_the_oracle_s_business():
    assert lost(H219, [X, R2, Y]) == []
    assert lost(H219, [Y, X, R2]) == []


@pytest.mark.parametrize("missing", [R2, X, Y])
def test_a_counterfactual_result_missing_a_side_s_line_reports_that_line(missing):
    merged = [R2, Y, X]
    merged.remove(missing)
    assert lost(H219, merged) == [missing]


def test_re_emitting_the_edited_base_line_is_over_production_not_a_loss():
    assert lost(H219, [R, R2, Y, X]) == []


def test_an_empty_result_reports_every_line_the_licence_requires():
    assert Counter(lost(H219, [])) == Counter([R2, Y, X])


# --- a let-go base line is allowed only when it is shaped ---------------------------------------

LET_GO = {
    "an ID row": ([D1, X], [D1], [D1_DONE, Y], D1_DONE),
    "a slug row": ([R, X], [R], [R2, Y], R2),
    "a dated log bullet": ([SEED, OURS], [SEED], [SEED2, THEIRS], SEED2),
    "a name-keyed log bullet": ([NAMED, OURS], [NAMED], [NAMED_DONE, THEIRS], NAMED_DONE),
}


@pytest.mark.parametrize("name", LET_GO)
def test_a_shaped_base_line_a_side_edited_is_let_go(name):
    ours, base, theirs, edit = LET_GO[name]
    h = hunk(ours, base, theirs)
    assert lost(h, [edit, theirs[1], ours[1]]) == []
    assert lost(h, [theirs[1], ours[1]]) == [edit]


def test_the_history_rewrite_lets_go_both_seed_lines():
    h = hunk([OURS, SEED2], [SEED, SEED2], [SEED, THEIRS])
    assert lost(h, [OURS, THEIRS]) == []
    assert lost(h, [OURS]) == [THEIRS]


UNSHAPED = {"prose": PROSE, "a separator row": DELIM, "a spaced separator row": SPACED_DELIM,
            "a header row": HEADER, "a blank line": ""}


@pytest.mark.parametrize("name", UNSHAPED)
def test_a_result_that_lets_go_an_unshaped_base_line_reports_it(name):
    line = UNSHAPED[name]
    h = hunk([R, X], [R, line], [R2, line])       # ours removed `line`, theirs kept it
    assert lost(h, [R2, X]) == [line], "the licence does not reach an unshaped line"
    assert lost(h, [R2, X, line]) == []
    assert lost(h, [X, line]) == [R2], "the shaped base line stays let go"


# --- row_slug_by_field --------------------------------------------------------------------------

@pytest.mark.parametrize("line,slug", [
    ("| `a-b` | x |", "a-b"),
    ("|`a-b`|x|", "a-b"),
    ("|   `a-b`   | x |", "a-b"),
    ("| `a-b` |", "a-b"),
    ("| `1a` | x |", "1a"),
    (R, "ci-settle"),
])
def test_row_slug_by_field_returns_the_slug(line, slug):
    assert oracle.row_slug_by_field(line) == slug


@pytest.mark.parametrize("line", [
    "| D1 | x |", "| `A` |", "| `A` | x |", "| `a_b` | x |", "| `-a` | x |", "| `` | x |",
    "| ` ` | x |", "| `a b` | x |", "| a-b | x |", "| `a-b | x |", "| a-b` | x |",
    "`a-b` | x |", "- `a-b` | x |", "| `a-b`", "|", "", DELIM, SPACED_DELIM, HEADER,
    "| 3 | x |", "| `é` | x |", "| `a-b` extra | x |",
])
def test_row_slug_by_field_is_none_for_anything_else(line):
    assert oracle.row_slug_by_field(line) is None


def test_a_slug_row_is_not_an_id_row_and_the_reverse():
    assert oracle.row_id_by_field(R) is None and oracle.row_slug_by_field(D1) is None


# --- every other label: the answer it had before ------------------------------------------------

def old_lost_lines(h, result):
    """The pre-4.4 body, copied here as the reference: no arm, no read of `hunk.base` of its own."""
    key = oracle.oracle_key(result.label, result.renumbered)
    ours = Counter(key(line) for line in h.ours)
    theirs = Counter(key(line) for line in h.theirs)
    collapsible = (oracle.collapsible_keys(h, key, result.label)
                   if result.label in oracle.MAY_COLLAPSE_A_CROSS_SIDE_DUPLICATE else set())
    need = Counter()
    for k in set(ours) | set(theirs):
        need[k] = (max(ours[k], theirs[k]) if collapsible is None or k in collapsible
                   else ours[k] + theirs[k])
    return list((need - Counter(key(line) for line in result.lines)).elements())


def fixture_hunks():
    return [seg for _name, text in ALL_FIXTURES
            for seg in classify_file(text).segments if isinstance(seg, Hunk)]


def test_every_other_label_reports_what_it_reported_before_on_the_fixture_corpus():
    labels = sorted((MECHANICAL | SEMANTIC) - {LABEL})
    population = fixture_hunks() + [H219]
    assert len(population) >= 10 and len(labels) >= 8, "the differential must not be vacuous"
    moved, reported = [], 0
    for h in population:
        for label in labels:
            for out in (list(h.ours), list(h.theirs), list(h.ours) + list(h.theirs), []):
                result = HunkResult(label, "RESOLVED", out)
                before = old_lost_lines(h, result)
                reported += bool(before)
                if oracle.lost_lines(h, result) != before:
                    moved.append((label, out[:2]))
    assert reported >= 10, "the corpus must exercise a non-empty report, not only []"
    assert not moved, moved[:6]


@pytest.mark.parametrize("label", sorted((MECHANICAL | SEMANTIC) - {LABEL}))
def test_no_other_label_takes_the_base_aware_arm_on_the_219_hunk(label):
    """Under the shaped label the edited `R` is let go (`[]` above); under any other the hunk is
    held to its identity, so the same merged lines lose the base line ours kept."""
    assert lost(H219, [R2, Y, X], label) == [R]
    assert lost(H219, [R, R2, Y, X], label) == []
