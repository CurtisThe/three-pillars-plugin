"""test_prose_question.py — the pure detector for a question left as prose.

design: seat-escalate-first 3.1 — `question_text(message, tail=16)` over plain strings
(the Stop hook hands over the assistant message; there is no pane chrome). A message that
ends in a "Needs your decision" block, or in two or more numbered or lettered options with
a question line directly above or below, yields a one-line summary; everything else yields
None. Oracle: example. Assertions go through the returned summary (its key words, its
single-line and length shape) and through metamorphic pairs (a re-indented or re-marked
copy of a message must answer like the original), never through a wording pin.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import prose_question as pq  # noqa: E402

INCIDENT = (
    "Rebase failed on #337.\n\n"
    "**Needs your decision:** which base?\n1. main\n2. release\n"
)
OPTIONS_UNDER_QUESTION = "Two ways forward.\nWhich option?\n1. Rebase\n2. Merge\n3. Stop\n"
OPTIONS_THEN_QUESTION = "1. Rebase\n2. Merge\n\nWhich do you want?\n"


# -- positives: a question for the operator is left as prose ------------------


def test_incident_shape_names_the_question():
    out = pq.question_text(INCIDENT)
    assert out is not None
    assert "which base" in out


def test_options_under_a_question_line():
    out = pq.question_text(OPTIONS_UNDER_QUESTION)
    assert out is not None
    assert "Which option" in out


def test_options_followed_by_one_final_question_line():
    out = pq.question_text(OPTIONS_THEN_QUESTION)
    assert out is not None
    assert "Which do you want" in out


def test_trailing_marker_line_ending_in_a_question_mark():
    out = pq.question_text("Rebase failed.\nNeeds your decision: which base?\n")
    assert out is not None
    assert "which base" in out


@pytest.mark.parametrize(
    "message",
    [
        "Which option?\n(a) Rebase\n(b) Merge\n",
        "Which option?\na. Rebase\nb. Merge\n",
        "Which option?\nA. Rebase\nB. Merge\n",
        "Which option?\na) Rebase\nb) Merge\n",
        "Which option?\n1) Rebase\n2) Merge\n",
    ],
)
def test_every_marker_family_counts_as_options(message):
    out = pq.question_text(message)
    assert out is not None
    assert "Which option" in out


def test_continuation_lines_indented_deeper_stay_inside_the_run():
    msg = "Which option?\n1. Rebase\n   keeps history\n2. Merge\n   one commit\n"
    out = pq.question_text(msg)
    assert out is not None
    assert "Which option" in out


def test_needs_your_decision_header_over_options_without_a_question_mark():
    out = pq.question_text("Rebase failed.\nNeeds your decision:\n1. main\n2. release\n")
    assert out is not None
    assert "Needs your decision" in out


# -- metamorphic: layout changes must not change the answer -------------------


def test_indented_options_answer_like_flush_options():
    flush = pq.question_text(OPTIONS_UNDER_QUESTION)
    indented = pq.question_text(
        OPTIONS_UNDER_QUESTION.replace("1. ", "  1. ").replace("2. ", "  2. ")
        .replace("3. ", "  3. ")
    )
    assert indented is not None
    assert indented == flush


def test_paren_markers_answer_like_dot_markers():
    dotted = pq.question_text(OPTIONS_UNDER_QUESTION)
    parens = pq.question_text(
        OPTIONS_UNDER_QUESTION.replace("1.", "1)").replace("2.", "2)").replace("3.", "3)")
    )
    assert parens == dotted


def test_earlier_prose_beyond_the_tail_does_not_change_the_answer():
    long_prefix = "".join(f"Working on step {i}.\n" for i in range(60))
    assert pq.question_text(long_prefix + INCIDENT) == pq.question_text(INCIDENT)


def test_tail_bounds_the_lines_considered():
    # Only the last two non-blank lines are looked at: the question line is cut off.
    assert pq.question_text(OPTIONS_UNDER_QUESTION, tail=2) is None
    assert pq.question_text(OPTIONS_UNDER_QUESTION, tail=16) is not None


# -- shape of the returned summary -------------------------------------------


@pytest.mark.parametrize(
    "message",
    [INCIDENT, OPTIONS_UNDER_QUESTION, OPTIONS_THEN_QUESTION],
)
def test_summary_is_one_line_with_no_bold_markup(message):
    out = pq.question_text(message)
    assert out is not None
    assert "\n" not in out
    assert "**" not in out
    assert out == out.strip()


def test_summary_is_capped_at_200_chars():
    long_question = "Which of these many things should we pick " + "really " * 80 + "now?"
    out = pq.question_text(f"{long_question}\n1. a\n2. b\n")
    assert out is not None
    assert len(out) <= 200
    assert out.startswith("Which of these")


# -- negatives: nothing the operator has to answer ----------------------------


@pytest.mark.parametrize(
    "message",
    [
        "Done. Tests pass.\n",
        # a numbered summary with no question line
        "Summary:\n1. Fixed X\n2. Fixed Y\n",
        # a plain closing question in running prose
        "I pushed the fix. Want me to run the suite again?\n",
        # options followed by more prose: the question is already answered
        "Which option?\n1. Rebase\n2. Merge\nI went with 1.\n",
        # the marker phrase mid-sentence, not a trailing ask
        "The run no longer needs your decision.\nAll green.\n",
        # a marker line that asks nothing
        "Needs your decision: none\n",
    ],
)
def test_no_question_for_the_operator(message):
    assert pq.question_text(message) is None


@pytest.mark.parametrize("message", [None, "", "\n\n  \n"])
def test_empty_input_is_none(message):
    assert pq.question_text(message) is None


def test_a_single_option_is_not_a_run():
    assert pq.question_text("Which option?\n1. Rebase\n") is None


def test_options_of_two_marker_families_are_not_one_run():
    assert pq.question_text("Which option?\n1. Rebase\nb. Merge\n") is None


def test_question_far_above_the_options_is_not_directly_above():
    msg = "Which option?\nHere is some context first.\n1. Rebase\n2. Merge\n"
    assert pq.question_text(msg) is None


# -- the question block: the lines the seat classifier reads (design 1.4 B3) -------------


def test_block_is_the_question_line_and_its_options_in_message_order():
    assert pq.question_block(OPTIONS_UNDER_QUESTION) == (
        "Which option?\n1. Rebase\n2. Merge\n3. Stop")


def test_block_is_the_run_then_the_final_question_line():
    assert pq.question_block(OPTIONS_THEN_QUESTION) == (
        "1. Rebase\n2. Merge\nWhich do you want?")


def test_block_keeps_an_option_continuation_line():
    msg = "Which option?\n1. Rebase\n   keeps history\n2. Merge\n"
    assert pq.question_block(msg) == "Which option?\n1. Rebase\nkeeps history\n2. Merge"


def test_block_strips_bold_markup_like_the_summary():
    assert pq.question_block(INCIDENT) == (
        "Needs your decision: which base?\n1. main\n2. release")


def test_block_bounds_by_the_same_tail_as_the_summary():
    assert pq.question_block(OPTIONS_UNDER_QUESTION, tail=2) is None
    assert pq.question_block(OPTIONS_UNDER_QUESTION, tail=16) is not None


@pytest.mark.parametrize("message", [None, "", "\n\n  \n"])
def test_block_of_empty_input_is_none(message):
    assert pq.question_block(message) is None
