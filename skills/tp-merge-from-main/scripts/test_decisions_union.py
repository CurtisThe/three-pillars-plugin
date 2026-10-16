"""`decisions_union.union_decisions`: the prefix test and the assembly.

Spec: basesync-three-way-verifier detailed-design.md Interfaces (`decisions_union.union_decisions`).
When the merge base is a line-prefix of both sides, the result is base plus both tails, each entry
verbatim: a continuation tail (one that does not open with a decision heading) goes first, each
heading tail gets one blank line before it, byte-equal tails are emitted once. Any other shape
returns None. Inputs are small hand-built documents and every expectation is traced by hand from
the spec (skills/_shared/test-fragility.md); each union result is also run through the independent
verifier, which must call it VERIFIED.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from decisions_union import union_decisions  # noqa: E402
from verify import VERIFIED, verify  # noqa: E402

BASE = "# Decisions\n\n### [tp-plan] first\n**Decided**: yes\n"
HEAD_O = "### [tp-ours] ours entry\n**Decided**: a\n"
HEAD_T = "### [tp-theirs] theirs entry\n**Decided**: b\n"
CONT = "**Outcome**: shipped\n"


def verified(base, ours, theirs, result):
    return verify(ours, theirs, result, base=base, mechanical_applied=True).verdict == VERIFIED


def test_two_heading_tails_are_base_ours_theirs_with_a_blank_before_each():
    ours, theirs = BASE + "\n" + HEAD_O, BASE + HEAD_T
    got = union_decisions(BASE, ours, theirs)
    assert got == BASE + "\n" + HEAD_O + "\n" + HEAD_T
    assert verified(BASE, ours, theirs, got)


def test_heading_tail_leading_blanks_are_stripped_to_exactly_one_blank():
    ours, theirs = BASE + "\n\n\n" + HEAD_O, BASE + HEAD_T
    assert union_decisions(BASE, ours, theirs) == BASE + "\n" + HEAD_O + "\n" + HEAD_T


def test_no_extra_blank_when_the_output_already_ends_with_one():
    base = BASE + "\n"
    ours, theirs = base + HEAD_O + "\n", base + HEAD_T
    got = union_decisions(base, ours, theirs)
    assert got == base + HEAD_O + "\n" + HEAD_T
    assert verified(base, ours, theirs, got)


def test_continuation_goes_first_verbatim_whichever_side_holds_it():
    ours, theirs = BASE + CONT, BASE + "\n" + HEAD_T
    want = BASE + CONT + "\n" + HEAD_T
    assert union_decisions(BASE, ours, theirs) == want
    assert union_decisions(BASE, theirs, ours) == want
    assert verified(BASE, ours, theirs, want)
    assert verified(BASE, theirs, ours, want)


def test_continuation_keeps_its_leading_blanks_as_base_plus_the_rest_of_the_side():
    cont_side = BASE + "\n\n" + CONT
    other = BASE + "\n" + HEAD_T
    got = union_decisions(BASE, cont_side, other)
    assert got == cont_side + "\n" + HEAD_T
    assert got.startswith(BASE + cont_side[len(BASE):])
    assert verified(BASE, cont_side, other, got)


def test_continuation_opening_with_a_blank_then_a_paragraph_keeps_that_blank():
    for last in ("| a | b |", "- item"):
        base = f"### [tp-plan] first\n{last}\n"
        cont_side = base + "\nA new paragraph.\n"
        other = base + "\n" + HEAD_T
        got = union_decisions(base, cont_side, other)
        assert got == base + "\nA new paragraph.\n" + "\n" + HEAD_T
        assert f"{last}\nA new" not in got
        assert verified(base, cont_side, other, got)


def test_two_continuation_tails_return_none():
    assert union_decisions(BASE, BASE + CONT, BASE + "**Why**: cost\n") is None


def test_base_not_a_prefix_of_either_side_returns_none():
    bad = "# Decisions\n\n### [tp-plan] first\n**Decided**: no\n" + HEAD_O
    good = BASE + HEAD_T
    assert union_decisions(BASE, bad, good) is None
    assert union_decisions(BASE, good, bad) is None


def test_an_empty_tail_returns_none():
    assert union_decisions(BASE, BASE, BASE + HEAD_T) is None
    assert union_decisions(BASE, BASE + HEAD_O, BASE) is None
    assert union_decisions(BASE, BASE, BASE) is None


def test_byte_equal_tails_are_emitted_once():
    ours = theirs = BASE + "\n" + HEAD_O
    got = union_decisions(BASE, ours, theirs)
    assert got == BASE + "\n" + HEAD_O
    assert got.count("ours entry") == 1
    assert verified(BASE, ours, theirs, got)


TAIL_206_O = (
    "### [tp-plan-audit] round 1 results\n"
    "| finding | verdict |\n|---|---|\n| F1 | bind |\n"
    "```python\nx = 1\n```\n"
    "- flag: --auto\n- flag: --spike\n"
    "<!-- keep: a note -->\n"
    "**Decided**: bind F1\n"
)
TAIL_206_T = (
    "### [tp-implement] worker flags\n"
    "- flag: --local\n"
    "```\nsh -c true\n```\n"
    "<!-- closed -->\n"
)


def test_the_206_shape_is_kept_verbatim():
    ours, theirs = BASE + "\n" + TAIL_206_O, BASE + "\n" + TAIL_206_T
    got = union_decisions(BASE, ours, theirs)
    assert got == BASE + "\n" + TAIL_206_O + "\n" + TAIL_206_T
    assert verified(BASE, ours, theirs, got)


def test_base_without_a_trailing_newline_still_unions_and_ends_with_one_newline():
    base = "# Decisions\n\n### [tp-plan] first\n**Decided**: yes"
    ours, theirs = base + "\n\n" + HEAD_O, base + "\n\n" + HEAD_T
    got = union_decisions(base, ours, theirs)
    assert got == base + "\n\n" + HEAD_O + "\n" + HEAD_T
    assert got.endswith("\n") and not got.endswith("\n\n")
    assert verified(base, ours, theirs, got)


def test_a_base_with_no_trailing_newline_must_equal_the_sides_last_shared_line():
    base = "### [tp-plan] first\n**Decided**: yes"
    changed = "### [tp-plan] first\n**Decided**: no\n\n" + HEAD_O
    assert union_decisions(base, changed, base + "\n\n" + HEAD_T) is None


def test_sides_without_a_final_newline_get_exactly_one_in_the_result():
    ours, theirs = BASE + "\n" + HEAD_O.rstrip("\n"), BASE + HEAD_T.rstrip("\n")
    got = union_decisions(BASE, ours, theirs)
    assert got.endswith("**Decided**: b\n") and not got.endswith("\n\n")


def test_a_terminal_newline_is_not_a_line_so_a_prefix_ending_in_one_still_matches():
    assert union_decisions("a\n", "a\nX\n", "a\n### [t] y\n") == "a\nX\n\n### [t] y\n"


def test_unicode_line_separators_stay_inside_their_lines():
    base = "### [tp-plan] first\nnote still one line\x0c\u0085\n"
    ours, theirs = base + "\n" + HEAD_O, base + HEAD_T
    assert union_decisions(base, ours, theirs) == base + "\n" + HEAD_O + "\n" + HEAD_T
