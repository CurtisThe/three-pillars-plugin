"""Tests for round_budget sticky terminals (check 0) and `holding`.

design: iterate-convergence-budget (Task 2.5)

A budget terminal is re-evaluated against the current `limits(config)` before
anything is counted: it holds (re-emitted, nothing counted or logged) while its
signal still fires, and lifts with a `[budget-lifted]` note once the operator
raises the limit or repairs the input.
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from round_budget import K_KEY, BudgetError, tick  # noqa: E402
from test_round_budget_kinds import BLOCK, CLEAN, NOW, PR, Loop, S  # noqa: E402

CAP7 = {"pdw": {"guards": {"round_cap": 7}}}


def at_round_cap(tmp_path) -> Loop:
    lp = Loop(tmp_path, iteration=5, budget_last_head="h5", budget_last_round="r5",
              budget_last_action="fix", budget_head_blocking=True)
    lp.step("h6", "r6", BLOCK)
    assert lp.term == "budget-exhausted" and lp.state["termination_reason"] == "round-cap"
    assert lp.at() == (6, 1) and len(lp.lines) == 1
    return lp


def lifted_notes(state):
    return [t for t in state.get("transitions", []) if "[budget-lifted]" in str(t.get("note"))]


def test_round_cap_reemitted_on_same_head_clean_reroll(tmp_path):
    lp = at_round_cap(tmp_path)
    lp.step("h6", "r6.1", CLEAN)
    assert lp.term == "budget-exhausted" and lp.state["termination_reason"] == "round-cap"
    assert lp.at() == (6, 1) and len(lp.lines) == 1  # nothing counted or logged
    assert lifted_notes(lp.state) == []


def _raise_cap_and_rereview(tmp_path) -> Loop:
    lp = at_round_cap(tmp_path)
    lp.config = CAP7
    lp.step("h6", "r7", BLOCK)
    assert lp.term is None
    assert lp.state["phase"] == "awaiting-review" and lp.state["termination_reason"] is None
    assert len(lifted_notes(lp.state)) == 1
    assert lp.at() == (6, 1)  # completion: iteration stays, no second k bump for h6
    assert lp.state["budget_last_action"] == "fix" and len(lp.lines) == 2
    return lp


def test_raise_round_cap_then_clean_round_7(tmp_path):
    lp = _raise_cap_and_rereview(tmp_path)
    lp.step("h7", "r8", CLEAN)
    assert lp.term is None and lp.at() == (7, 0)


def test_raise_round_cap_then_blocking_round_7(tmp_path):
    lp = _raise_cap_and_rereview(tmp_path)
    lp.step("h7", "r8", BLOCK)
    assert lp.term == "budget-exhausted" and lp.state["termination_reason"] == "round-cap"
    assert lp.state["iteration"] == 7


def test_raise_k_consecutive_lifts(tmp_path):
    lp = Loop(tmp_path, iteration=3, phase="convergence-failure",
              termination_reason="k-consecutive", budget_last_head="h3",
              budget_last_round="r3", budget_last_action="noop", budget_head_blocking=True,
              **{K_KEY: 3})
    lp.step("h3", "r3.1", CLEAN)  # a clean re-roll must not escape k-consecutive
    assert lp.term == "convergence-failure" and lp.at() == (3, 3)
    lp.config = {"pdw": {"guards": {"k_consecutive": 4}}}
    lp.step("h3", "r3.2", BLOCK)
    assert lp.term is None and lp.at() == (3, 3)
    assert len(lifted_notes(lp.state)) == 1


def _tick(state, config=None, numstat_fn=None, base=None, tally=CLEAN, ordinal="r2"):
    return tick(state, head_sha="h1", pr_url=PR, tally=tally, review_base=base, config=config,
                now=NOW, ordinal=ordinal, numstat_fn=numstat_fn)


def test_wall_clock_holds_then_lifts():
    started = (NOW - timedelta(seconds=20000)).isoformat()
    state = S(iteration=2, phase="cap-exhausted", termination_reason="wall-clock",
              started_at=started, budget_last_head="h1", budget_last_round="r1")
    st, term, detail = _tick(state)
    assert term == "cap-exhausted" and detail["holding"] == ["wall-clock"]
    st, term, _ = _tick(state, config={"pdw": {"guards": {"wall_clock_sec": 30000}}})
    assert term is None and st["phase"] == "awaiting-review"


def test_budget_error_holds_while_numstat_raises_then_lifts():
    state = S(iteration=2, phase="budget-exhausted", termination_reason="budget-error",
              budget_last_head="h1", budget_last_round="r1")

    def boom(a, b):
        raise BudgetError("unfetchable base")
    _, term, detail = _tick(state, numstat_fn=boom, base="BASE")
    assert term == "budget-exhausted" and detail["signal"] == "budget-error"
    st, term, _ = _tick(state, numstat_fn=lambda a, b: [], base="BASE")
    assert term is None and st["termination_reason"] is None


def test_budget_error_corrupt_started_at_holds_until_deleted():
    state = S(iteration=2, phase="budget-exhausted", termination_reason="budget-error",
              started_at="garbage", budget_last_head="h1", budget_last_round="r1")
    _, term, _ = _tick(state)
    assert term == "budget-exhausted"
    del state["started_at"]
    st, term, _ = _tick(state)
    assert term is None and st["started_at"] == NOW.isoformat()


def test_growth_terminal_holds_without_numstat_or_base():
    state = S(iteration=2, phase="budget-exhausted", termination_reason="growth-lines",
              original_diff_lines=100, budget_baseline_head="h0",
              budget_baseline_split={"test_added": 0, "code_added": 100},
              budget_last_head="h1", budget_last_round="r1")
    for fn, base in ((None, "BASE"), (lambda a, b: [], None), (None, None)):
        _, term, detail = _tick(state, numstat_fn=fn, base=base)
        assert term == "budget-exhausted" and detail["signal"] == "growth-lines"
    big = lambda a, b: [("src/a.py", 200, 0)]  # noqa: E731
    _, term, _ = _tick(state, numstat_fn=big, base="BASE")
    assert term == "budget-exhausted"
    st, term, _ = _tick(state, numstat_fn=big, base="BASE",
                        config={"pdw": {"guards": {"growth_multiplier": 3}}})
    assert term is None and st["phase"] == "awaiting-review"


def test_holding_lists_round_cap_and_k(tmp_path):
    lp = Loop(tmp_path, iteration=5, budget_last_head="h5", budget_last_round="r5",
              budget_last_action="fix", **{K_KEY: 2})
    st, term, detail = tick(lp.state, head_sha="h6", pr_url=PR, tally=BLOCK, review_base=None,
                            config=None, now=NOW, ordinal="r6")
    assert term == "budget-exhausted" and detail["signal"] == "round-cap"
    assert detail["holding"] == ["round-cap", "k-consecutive"]
    # re-emitted on a re-roll, still listing both
    st = {**st, "budget_last_head": "h6", "budget_last_round": "r6", "budget_last_action": "noop"}
    _, term, detail = tick(st, head_sha="h6", pr_url=PR, tally=CLEAN, review_base=None,
                           config=None, now=NOW, ordinal="r6.1")
    assert term == "budget-exhausted"
    assert detail["holding"] == ["round-cap", "k-consecutive"]
