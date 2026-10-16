"""Review weight sets the round cap — pr-loop §D5, Behavior 12.

`limits(config, state)` reads `state["review_weight"]` BEFORE the `pdw.guards`
overlay, so just-do-it converges in 2 rounds while light/spike/full keep the new
default 3 — and an explicit `pdw.guards.round_cap` still wins over the weight.
Run with: python3 -m pytest skills/tp-pr-iterate/scripts/test_round_budget_weight.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import round_budget as rb  # noqa: E402

NOW = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)
PR = "https://github.com/o/r/pull/7"
GUARD5 = {"pdw": {"guards": {"round_cap": 5}}}


def T(blocking=0, degraded=0):
    return {"P": 0, "X": 0, "T": 0, "C": 0, "blocking": blocking, "degraded": degraded}


def S(**kw):
    base = {"phase": "awaiting-review", "iteration": 0, "started_at": NOW.isoformat(),
            "consecutive_codereview_structural_rounds": 0, "budget_pr_url": PR,
            "budget_last_head": None, "budget_last_round": None, "budget_last_action": None}
    base.update(kw)
    return base


def run(state, head, tally, config=None, ordinal="r1"):
    return rb.tick(state, head_sha=head, pr_url=PR, tally=tally, review_base=None,
                   config=config, now=NOW, ordinal=ordinal)


# ---------- limits: the weight table ----------


@pytest.mark.parametrize("weight,cap", [("just-do-it", 2), ("light", 3), ("spike", 3),
                                        ("full", 3)])
def test_limits_round_cap_by_review_weight(weight, cap):
    assert rb.limits({}, {"review_weight": weight})["round_cap"] == cap


@pytest.mark.parametrize("weight", ["just-do-it", "light", "full"])
def test_limits_explicit_guard_beats_the_weight(weight):
    assert rb.limits(GUARD5, {"review_weight": weight})["round_cap"] == 5


@pytest.mark.parametrize("state", [{}, {"review_weight": None}, {"review_weight": "huge"}])
def test_limits_no_or_unknown_weight_keeps_the_default_cap(state):
    assert rb.limits({}, state)["round_cap"] == 3


def test_weight_round_caps_is_the_d5_table():
    assert rb.WEIGHT_ROUND_CAPS == {"just-do-it": 2, "light": 3, "spike": 3, "full": 3}


# ---------- tick: just-do-it stops after 2 rounds, light/full at 3 ----------


def test_tick_just_do_it_blocking_at_two_iterations_fires():
    st, term, detail = run(S(iteration=1, review_weight="just-do-it"), "h2", T(blocking=1))
    assert st["iteration"] == 2 and term == "budget-exhausted"
    assert st["termination_reason"] == "round-cap"
    assert detail["round_cap"] == 2 and detail["measured"] == 2 and detail["limit"] == 2


def test_tick_just_do_it_below_two_no_terminal():
    st, term, _ = run(S(review_weight="just-do-it"), "h1", T(blocking=1))
    assert st["iteration"] == 1 and term is None


@pytest.mark.parametrize("weight", ["light", "full"])
def test_tick_light_and_full_stop_at_three(weight):
    st, term, detail = run(S(iteration=2, budget_last_head="h2", review_weight=weight),
                           "h3", T(blocking=1))
    assert st["iteration"] == 3 and term == "budget-exhausted"
    assert detail["round_cap"] == 3 and detail["measured"] == 3 and detail["limit"] == 3
    st, term, _ = run(S(iteration=1, budget_last_head="h1", review_weight=weight),
                      "h2", T(blocking=1))
    assert st["iteration"] == 2 and term is None


def test_tick_guard_wins_over_the_weight():
    st, term, detail = run(S(iteration=2, review_weight="just-do-it"), "h3", T(blocking=1),
                           config=GUARD5)
    assert st["iteration"] == 3 and term is None
    assert detail["round_cap"] == 5
