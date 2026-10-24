"""test_prose_question_more.py — bullet options under a marker; negated markers (check C2, C3).

design: seat-escalate-first Phase 3 check. Pure strings; no I/O.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from prose_question import question_text  # noqa: E402


@pytest.mark.parametrize("message", [
    "Rebase failed on #337.\n\n**Needs your decision:** which base?\n- main\n- release\n",
    "Needs your decision: which base?\n* main\n* release\n",
    "**Needs your decision**\n- main\n  keeps history\n- release\n",
    "  Needs your decision: which base?\n  - main\n  - release\n",
], ids=["dash", "star", "bare-marker-header", "indented"])
def test_bullet_options_under_a_marker_are_a_question(message):
    found = question_text(message)
    assert found and "\n" not in found
    assert "needs your decision" in found.lower()


@pytest.mark.parametrize("message", [
    "Why did it fail?\n- the lock was stale\n- the base moved\n",      # explanatory list
    "Which option?\n- main\n- release\n",                              # bullets need the marker
    "Needs your decision: which base?\n- main\n- release\nI chose main.\n",  # more prose
    "Needs your decision: which base?\n- main\n",                      # one bullet is no run
    "Changes:\n- fixed X\n- fixed Y\n",
], ids=["why-list", "plain-question-bullets", "trailing-prose", "single-bullet", "summary"])
def test_bullets_without_a_marker_line_are_not_a_question(message):
    assert question_text(message) is None


@pytest.mark.parametrize("message", [
    "None of these needs your decision:\n1. fixed X\n2. fixed Y\n",
    "Nothing here needs your decision:\n- fixed X\n- fixed Y\n",
    "This never needs your decision:\n1. a\n2. b\n",
    "No item needs your decision: which base?\n",
], ids=["none-of", "nothing-here", "never", "no-item-last-line"])
def test_a_negated_marker_is_not_a_question(message):
    assert question_text(message) is None


def test_a_far_earlier_negation_does_not_hide_the_marker():
    message = "No fix worked after three tries, so this one needs your decision: which base?\n"
    assert question_text(message) is not None
