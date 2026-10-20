"""The `low-count-line` predicate and merge (`keyed_classes`) — the pure half, no wiring.

`three-pillars-docs/known_issues.md` carries one `N Low issues → …` count line under its Medium
entries. Both sides of a base-sync edit the number, so the hunk defers as `generic-prose`. The value
is derivable — `ours + theirs − base` — and the shape is checkable: a 3-way region whose base is
exactly that one line, each side being whole keyed entries (optional) and then the count line, with
the same text after the number on both sides and a heading (or EOF) below the region.

Every case builds a `conflict_parse.Hunk` by hand, so `base_marker` and `post_context` are the values
the predicate reads. The two accepted shapes are the 10-16 replays' `306` and `308a` KI hunks
(`test_replay_history_syncs.py` `PAIRS`). Task 2.3 wired the class into `extra_label`, so the
pin below asserts the label it names now — the pure half stays everything else in this file.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from conflict_parse import Hunk  # noqa: E402
from keyed_classes import (  # noqa: E402
    COUNT_LINE, LOW_COUNT_LABEL, extra_label, is_low_count_line, low_count_value,
    merge_low_count_lines,
)

# The text after the number, verbatim from `known_issues.md` (the plan's shared facts).
REST = ("Low issues → [known_issues_low.md](known_issues_low.md) (one line each; promote a Low "
        "to Medium by moving its entry back into this doc in the same commit).")


def C(n):
    return f"{n} {REST}"


def hunk(ours, theirs, base, post="## History", three_way=True):
    """A hand-built 3-way `Hunk`: `ours`/`base`/`theirs` are line LISTS, `post` the first non-blank
    line after the region (`None` = unknown)."""
    return Hunk(ours=list(ours), base=list(base), theirs=list(theirs),
                base_marker="||||||| base" if three_way else None, post_context=post)


# The two replays' shapes. 308a: the count line alone on all three sides (223 + 224 − 219 = 228).
H308A = lambda: hunk([C(223)], [C(224)], [C(219)])              # noqa: E731,E501
# 306: theirs also inserted two entries; 215 + 222 − 213 = 224.
H306 = lambda: hunk([C(215)],                                   # noqa: E731,E501
                    ["### M77: a", "- b", "", "### M78: c", "- d", "", C(222)],
                    [C(213)])
# 306 with entries on both sides: M80 is ours', M77/M78 theirs'.
H306_BOTH = lambda: hunk(["### M80: e", "- f", "", C(215)],     # noqa: E731,E501
                         ["### M77: a", "- b", "", "### M78: c", "- d", "", C(222)],
                         [C(213)])


def test_regex_groups_are_the_number_and_the_text_after_the_arrow():
    m = COUNT_LINE.match(C(249))
    assert m.group(1) == "249"
    assert f"{m.group(1)} Low issues \u2192 {m.group(2)}" == C(249)
    assert COUNT_LINE.match("Low issues → x") is None           # no number
    assert COUNT_LINE.match("249 low issues → x") is None       # wrong case
    assert COUNT_LINE.match(" 249 Low issues → x") is None      # indented
    assert COUNT_LINE.match("249 Low issues → x\r") is None     # a CR inside the line


def test_accepts_the_308a_shape_and_the_306_shape():
    assert is_low_count_line(H308A())
    assert is_low_count_line(H306())
    assert is_low_count_line(H306_BOTH())


@pytest.mark.parametrize("h", [H308A, H306, H306_BOTH])
def test_extra_label_names_the_class_for_each_accepted_shape(h):
    """Task 2.3 wired the class: `extra_label` checks `is_low_count_line` FIRST, so a count-line
    region that also carries keyed entries takes this label instead of `keyed-heading-insertion`."""
    assert extra_label(h()) == LOW_COUNT_LABEL
    assert LOW_COUNT_LABEL == "low-count-line"


def test_value_is_ours_plus_theirs_minus_base():
    assert low_count_value(H308A()) == 228
    assert low_count_value(H306()) == 224
    assert low_count_value(H306_BOTH()) == 224


def test_merge_of_308a_is_one_count_line():
    assert merge_low_count_lines(H308A()) == [C(228)]


def test_merge_of_306_keeps_theirs_entries_then_the_count_line():
    assert merge_low_count_lines(H306()) == [
        "### M77: a", "- b", "", "### M78: c", "- d", "", C(224)]


def test_merge_sorts_the_numbered_entries_and_puts_the_count_line_last():
    assert merge_low_count_lines(H306_BOTH()) == [
        "### M77: a", "- b", "", "### M78: c", "- d", "", "### M80: e", "- f", "", C(224)]


def test_merge_counts_arithmetically_and_keeps_ours_text_after_the_number():
    """The count is `ours + theirs − base`, not a recount of the region: the entries merged here are
    Medium ones, and the line's own text is ours' verbatim."""
    got = merge_low_count_lines(H306_BOTH())
    assert got[-1] == C(224) == f"{215 + 222 - 213} {REST}"


@pytest.mark.parametrize("kw", [{"three_way": False}])
def test_refuses_a_two_way_region(kw):
    assert not is_low_count_line(hunk([C(223)], [C(224)], [C(219)], **kw))


@pytest.mark.parametrize("base", [
    [],                                   # an empty base section
    ["249 Low issues"],                   # not a count line
    ["prose line"],
    [C(219), C(220)],                     # two count lines
    [C(219), ""],                         # a count line then a blank
    ["", C(219)],
    [C(219) + "\r"],                      # a carriage return on the base line
])
def test_refuses_a_base_that_is_not_exactly_one_count_line(base):
    assert not is_low_count_line(hunk([C(223)], [C(224)], base))


@pytest.mark.parametrize("ours,theirs", [
    ([C(223)], [C(224) + " extra"]),                       # the rest differs
    ([C(223) + " extra"], [C(224)]),
    ([C(223)], [C(224).replace("→", "->")]),               # a different arrow
    ([C(223)], ["### M77: a", "- b", C(224)]),             # no blank before the count line
    (["### M77: a", "- b", C(223)], [C(224)]),
    ([C(223), "trailing prose"], [C(224)]),                # the count line is not last
    ([C(223)], [C(224), "trailing prose"]),
    ([C(223), C(224)], [C(224)]),                          # a second count line on a side
    ([C(223)], [C(224), C(225)]),
    ([C(223) + "\r"], [C(224)]),                           # a CR inside a count line
    (["prose", "", C(223)], [C(224)]),                     # entries do not start at a keyed heading
    (["- a bullet", "", C(223)], [C(224)]),
    ([C(223)], ["## Medium", "", C(224)]),                 # a section heading, not an entry
])
def test_refuses_anything_but_a_count_line_and_whole_keyed_entries(ours, theirs):
    assert not is_low_count_line(hunk(ours, theirs, [C(219)]))


def test_refuses_the_same_key_on_both_sides():
    """A key on both sides is the gated `id-renumber-collision` shape, never a keep-both."""
    ours = ["### M77: ours", "- b", "", C(215)]
    theirs = ["### M77: theirs", "- b", "", C(222)]
    assert not is_low_count_line(hunk(ours, theirs, [C(213)]))


def test_refuses_a_negative_value():
    assert low_count_value(hunk([C(100)], [C(100)], [C(300)])) is None
    assert not is_low_count_line(hunk([C(100)], [C(100)], [C(300)]))


@pytest.mark.parametrize("post", ["## History", "# Title", "### M82: later entry", "", None])
def test_boundary_after_the_region_is_a_heading_or_eof_or_unknown(post):
    """A level 1-3 heading below the region means the count line still ends its section after the
    merge; a blank-only run to EOF does too. `None` (another region follows) is unknown, refused."""
    accepted = is_low_count_line(hunk([C(223)], [C(224)], [C(219)], post=post))
    assert accepted is (post is not None)


@pytest.mark.parametrize("post", ["prose line below", "- a bullet", "    ## indented heading"])
def test_refuses_a_prose_line_after_the_region(post):
    assert not is_low_count_line(hunk([C(223)], [C(224)], [C(219)], post=post))


@pytest.mark.parametrize("h", [H308A, H306, H306_BOTH])
def test_a_hunk_outside_the_shape_keeps_both_sides_lines(h):
    """The merge is total like `merge_last_updated_lines`: an unrecognised hunk returns ours then
    theirs verbatim, so nothing is dropped by calling it on a hunk the predicate refused."""
    bad = h()
    bad.base = ["prose line"]
    assert not is_low_count_line(bad)
    assert merge_low_count_lines(bad) == bad.ours + bad.theirs


def test_merge_invents_no_line_and_drops_only_the_two_count_lines():
    got = merge_low_count_lines(H306_BOTH())
    entries = [ln for ln in got if not COUNT_LINE.match(ln)]
    ours_entries = [ln for ln in H306_BOTH().ours if not COUNT_LINE.match(ln)]
    theirs_entries = [ln for ln in H306_BOTH().theirs if not COUNT_LINE.match(ln)]
    assert sorted(entries) == sorted(ours_entries + theirs_entries)
    assert sum(1 for ln in got if COUNT_LINE.match(ln)) == 1
