"""Task 1.2 — the `last-updated-preamble` predicate and merge (`keyed_classes`), plus the two
dispatch helpers `classify` wires in (`extra_label`, `extra_confident`).

A `*Last updated: YYYY-MM-DD …*` line is the one preamble line almost every living doc carries, so
two branches that each touched it conflict. The class accepts only the exact shape: ours and theirs
each ONE line matching `LAST_UPDATED`, and base empty or one `*Last updated:` line. The merge takes
the later date and keeps both summaries.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from keyed_classes import (  # noqa: E402
    LAST_UPDATED, extra_confident, extra_label, is_last_updated_preamble, merge_last_updated_lines,
)
from test_keyed_heading_class import ENTRY_A, ENTRY_B, make_hunk  # noqa: E402

BASE = "*Last updated: 2026-09-01*\n"
D29 = "*Last updated: 2026-09-29*\n"
D30 = "*Last updated: 2026-09-30*\n"


def preamble(ours, theirs, base=BASE, **kw):
    return make_hunk(ours, theirs, base=base, **kw)


@pytest.mark.parametrize("ours,theirs,base", [
    (D29, D30, BASE),
    (D29, D30, ""),                                                    # base empty
    ("*Last updated: 2026-09-29 — design-a: x*\n", "*Last updated: 2026-09-30 (y)*\n", BASE),
    ("*Last updated: 2026-09-29*  \n", D30, "*Last updated: 2026-09-01 — old*\n"),   # trailing space
    (D30, D30, BASE),                                                  # identical lines
])
def test_accepts_one_last_updated_line_per_side(ours, theirs, base):
    assert is_last_updated_preamble(preamble(ours, theirs, base))


def test_refuses_a_two_way_region():
    assert not is_last_updated_preamble(preamble(D29, D30, three_way=False))


@pytest.mark.parametrize("ours,theirs", [
    (D29 + "\n", D30),                       # an extra blank line
    (D29, D30 + "\n"),
    (D29 + "A paragraph line.\n", D30),
    (D29, "intro\n" + D30),
    (D29 + D29, D30),                        # two preamble lines
    ("", D30),                               # an empty side
    (D29, ""),
])
def test_refuses_any_extra_or_missing_line(ours, theirs):
    assert not is_last_updated_preamble(preamble(ours, theirs))


@pytest.mark.parametrize("base", [BASE + BASE, BASE + "\n", "\n", "# Title\n", "Last updated: x\n"])
def test_refuses_a_base_that_is_not_empty_or_one_last_updated_line(base):
    assert not is_last_updated_preamble(preamble(D29, D30, base))


@pytest.mark.parametrize("line", [
    "*Last updated: soon*\n",                # no date
    "*Last updated: 2026-9-29*\n",
    "*Last updated: 2026-09-29\n",           # no closing asterisk
    "Last updated: 2026-09-29*\n",           # no opening asterisk
    "*last updated: 2026-09-29*\n",          # wrong case
    "*Last updated:2026-09-29*\n",           # no space after the colon
    "*Last updated: 2026-09-29* trailing\n",
    "*Last updated: 2026-09-29*\r\n",        # a carriage return is not whitespace here
    " *Last updated: 2026-09-29*\n",
])
def test_refuses_a_line_that_is_not_the_exact_shape(line):
    assert not is_last_updated_preamble(preamble(line, D30))
    assert not is_last_updated_preamble(preamble(D30, line))


def test_regex_groups_are_the_date_and_the_rest():
    m = LAST_UPDATED.match("*Last updated: 2026-09-29 — design-a: **x***")
    assert (m.group(1), m.group(2)) == ("2026-09-29", " — design-a: **x**")
    m = LAST_UPDATED.match("*Last updated: 2026-09-29*")
    assert (m.group(1), m.group(2)) == ("2026-09-29", "")


def merged(ours, theirs, base=BASE):
    h = preamble(ours, theirs, base)
    assert is_last_updated_preamble(h)
    return merge_last_updated_lines(h)


def test_same_rest_takes_the_later_dated_line_verbatim():
    assert merged("*Last updated: 2026-09-29 — x*\n", "*Last updated: 2026-09-30 — x*\n") \
        == ["*Last updated: 2026-09-30 — x*"]
    assert merged("*Last updated: 2026-10-01 — x*\n", "*Last updated: 2026-09-30 — x*\n") \
        == ["*Last updated: 2026-10-01 — x*"]
    assert merged(D29, D30) == ["*Last updated: 2026-09-30*"]


def test_a_tie_on_the_date_with_the_same_rest_takes_ours():
    assert merged("*Last updated: 2026-09-30 — x*  \n", "*Last updated: 2026-09-30 — x*\n") \
        == ["*Last updated: 2026-09-30 — x*  "]


def test_different_rests_keep_both_summaries_under_the_later_date():
    ours = "*Last updated: 2026-09-29 — design-a landed*\n"
    theirs = "*Last updated: 2026-09-30 (design-b landed)*\n"
    assert merged(ours, theirs) == ["*Last updated: 2026-09-30 (design-b landed); design-a landed*"]
    assert merged(theirs, ours) == ["*Last updated: 2026-09-30 (design-b landed); design-a landed*"]


def test_the_other_rest_loses_spaces_and_one_leading_dash_of_either_kind():
    later = "*Last updated: 2026-09-30: a*\n"
    for other in ("2026-09-01 — b", "2026-09-01 - b", "2026-09-01   —   b  ", "2026-09-01 b"):
        assert merged(f"*Last updated: {other}*\n", later) == ["*Last updated: 2026-09-30: a; b*"]


def test_a_tie_on_the_date_with_different_rests_puts_ours_first():
    got = merged("*Last updated: 2026-09-30 — ours*\n", "*Last updated: 2026-09-30 — theirs*\n")
    assert got == ["*Last updated: 2026-09-30 — ours; theirs*"]


def test_a_date_only_side_adds_nothing_to_the_other_summary():
    assert merged("*Last updated: 2026-09-29*\n", "*Last updated: 2026-09-30 — theirs*\n") \
        == ["*Last updated: 2026-09-30 — theirs*"]
    assert merged("*Last updated: 2026-09-30*\n", "*Last updated: 2026-09-29 — theirs*\n") \
        == ["*Last updated: 2026-09-30; theirs*"]


def test_merge_returns_one_line_that_matches_the_class_shape():
    got = merged("*Last updated: 2026-09-29 — a*\n", "*Last updated: 2026-09-30 — b*\n")
    assert len(got) == 1 and LAST_UPDATED.match(got[0])


def test_extra_label_names_the_two_classes_and_nothing_else():
    assert extra_label(preamble(D29, D30)) == "last-updated-preamble"
    assert extra_label(make_hunk(ENTRY_A, ENTRY_B)) == "keyed-heading-insertion"
    assert extra_label(make_hunk("plain a\n", "plain b\n", base="plain\n")) is None
    assert extra_label(make_hunk(ENTRY_A, "### M48: dup\nx\n\n")) is None      # same key: gated class


def test_extra_confident_re_verifies_only_the_two_labels():
    h = preamble(D29, D30)
    h.label = "last-updated-preamble"
    assert extra_confident(h) is True
    h.ours = [D29.rstrip(), "extra line"]                  # no longer the exact shape
    assert extra_confident(h) is False

    k = make_hunk(ENTRY_A, ENTRY_B)
    k.label = "keyed-heading-insertion"
    assert extra_confident(k) is True
    k.theirs = ["### M48: dup", "x"]                        # now the same key as ours
    assert extra_confident(k) is False

    for label in ("", "preamble", "log-entry-insertion", "generic-prose", "id-renumber-collision"):
        k.label = label
        assert extra_confident(k) is None
