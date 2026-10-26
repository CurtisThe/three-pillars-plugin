"""test_stop_question_seat_route.py — the seat's prose question is classified once.

design: seat-scope-interactive-questions 1.4 (B5) — a seat turn ending on a prose question
is blocked once, classified over its question block (the question line plus its option
lines, `prose_question.question_block`) plus any `ruling:` line in the 16-line window:
run-bound names `/tp-escalate`, operator-direct names an `AskUserQuestion` card and never
`/tp-escalate`. Context prose above the question is in neither span. Reuses
`test_stop_question_hook`'s fixtures; explicit env, git calls scrubbed as `clean_git_env`
does, no network. Oracle: example.
test-fragility.md: assertions go through the decision and the route the reason names, never
a full-sentence pin.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import prose_question as pq  # noqa: E402
from test_stop_question_hook import (  # noqa: E402
    Q, SEAT, _base, _reason, _stop, _worktree)

CARD = "AskUserQuestion"
ESCALATE = "/tp-escalate"
Q_DEMO = "Two ways forward.\nWhich option?\n1. Rebase demo\n2. Merge\n"
RULING = "ruling: demo-20261021-abcdef"
Q_RULING = "Two ways forward.\n%s\nWhich option?\n1. Rebase\n2. Merge\n" % RULING


def _card_parts(reason):
    assert ESCALATE not in reason
    for part in (CARD, "card"):
        assert part in reason


def _escalate_parts(reason):
    assert ESCALATE in reason
    for part in ("<slug|seat>", "--question"):
        assert part in reason


# --- (a) operator-direct: the block points at a card ------------------------------------

def test_a_seat_question_naming_no_live_run_is_pointed_at_a_card(tmp_path):
    base = _base(tmp_path)
    out, rc = _stop(base, SEAT)
    assert rc == 0
    reason = _reason(out)
    _card_parts(reason)
    assert "Which option?" in reason  # the question is echoed back
    assert "seat-allow" not in reason


# --- (b) run-bound: the block names /tp-escalate ----------------------------------------

@pytest.mark.parametrize("text", [
    "Two ways forward.\nWhich option for Demo?\n1. Rebase\n2. Merge\n",
    Q_DEMO,
])
def test_a_seat_question_naming_a_live_run_keeps_the_escalate_route(tmp_path, text):
    base = _base(tmp_path)
    _worktree(tmp_path, base)
    out, rc = _stop(base, SEAT, text)
    assert rc == 0
    _escalate_parts(_reason(out))


# --- (c) the live slug is read only in the question block --------------------------------

def test_a_live_slug_on_the_context_line_above_the_question_is_operator_direct(tmp_path):
    base = _base(tmp_path)
    _worktree(tmp_path, base)
    out, rc = _stop(base, SEAT, "The demo run is stalled.\n" + Q)
    assert rc == 0
    _card_parts(_reason(out))


# --- (d) a `ruling:` line in the window is run-bound -------------------------------------

def test_a_ruling_line_above_the_question_block_keeps_the_escalate_route(tmp_path):
    base = _base(tmp_path)
    out, rc = _stop(base, SEAT, Q_RULING)
    assert rc == 0
    _escalate_parts(_reason(out))


# --- (e) a seat by fallback rule 3 classifies the same way -------------------------------

def test_a_fallback_seat_gets_the_card_route_and_a_named_run_the_escalate_route(tmp_path):
    base = _base(tmp_path)
    _worktree(tmp_path, base)
    out, rc = _stop(base, {}, Q)
    assert rc == 0
    _card_parts(_reason(out))
    out, rc = _stop(base, {}, Q_DEMO)
    assert rc == 0
    _escalate_parts(_reason(out))


# --- (f) question_block: the question line and its options, in message order -------------

@pytest.mark.parametrize("message,block", [
    (Q, "Which option?\n1. Rebase\n2. Merge"),
    ("Two ways.\n1. Rebase\n2. Merge\nWhich option?", "1. Rebase\n2. Merge\nWhich option?"),
    ("Needs your decision:\n- Rebase\n- Merge", "Needs your decision:\n- Rebase\n- Merge"),
    ("Context.\nNeeds your decision: rebase or merge?",
     "Needs your decision: rebase or merge?"),
    ("Needs your decision:\n1. Rebase\n   keeps history\n2. Merge",
     "Needs your decision:\n1. Rebase\nkeeps history\n2. Merge"),
    ("**Needs your decision:** which base?\n1. main\n2. release\n",
     "Needs your decision: which base?\n1. main\n2. release"),
])
def test_question_block_returns_the_question_line_and_its_options(message, block):
    assert pq.question_block(message) == block


@pytest.mark.parametrize("message", [
    "Done. Tests pass.\n",
    "Summary:\n1. Fixed X\n2. Fixed Y\n",
    "I pushed the fix. Want me to run the suite again?\n",
    "Which option?\n1. Rebase\n2. Merge\nI went with 1.\n",
    "Which option?\n1. Rebase\n",
    "Which option?\n1. Rebase\nb. Merge\n",
    "Which option?\nHere is some context first.\n1. Rebase\n2. Merge\n",
    "Why did it fail?\n- the lock was stale\n- the base moved\n",
    "Which option?\n- main\n- release\n",
    "None of these needs your decision:\n1. fixed X\n2. fixed Y\n",
    "",
])
def test_question_block_is_none_wherever_question_text_is_none(message):
    assert pq.question_block(message) is None
    assert pq.question_text(message) is None


@pytest.mark.parametrize("message", [
    Q,
    "Two ways.\n1. Rebase\n2. Merge\nWhich option?",
    "Needs your decision:\n- Rebase\n- Merge",
    "Context.\nNeeds your decision: rebase or merge?",
    "Two ways forward.\nWhich option for Demo?\n1. Rebase\n2. Merge\n",
    Q_RULING,
])
def test_question_block_and_question_text_answer_on_the_same_question(message):
    block, summary = pq.question_block(message), pq.question_text(message)
    assert block is not None and summary is not None
    assert summary in " ".join(block.split())
