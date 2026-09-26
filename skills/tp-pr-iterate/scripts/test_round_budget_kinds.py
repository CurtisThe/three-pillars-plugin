"""Tests for round_budget round kinds and the k-counter — `[Q2]` `[Q4]`.

design: iterate-convergence-budget (Task 2.3)

Round kinds: **counted** (new head, or a new ordinal after a `fix`), **completion**
(same head, new ordinal, not degraded-only) and **re-shell** (same ordinal, or no
ordinal). Multi-step tests drive `step`, which calls `tick` then replays
loop_driver's writes (`budget_last_head/round/action`, A6).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from round_budget import K_KEY, tick  # noqa: E402

NOW = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)
PR = "https://github.com/o/r/pull/7"


def T(blocking=0, degraded=0):
    return {"P": 0, "X": 0, "T": 0, "C": blocking, "blocking": blocking, "degraded": degraded}


BLOCK, CLEAN, DEGR = T(blocking=1), T(), T(degraded=1)


def S(**kw):
    base = {"phase": "awaiting-review", "iteration": 0, "started_at": NOW.isoformat(),
            K_KEY: 0, "budget_pr_url": PR, "budget_last_head": None,
            "budget_last_round": None, "budget_last_action": None,
            "budget_head_blocking": None}
    base.update(kw)
    return base


class Loop:
    """Holds the state and class log; `step` = tick + loop_driver's A6 writes."""

    def __init__(self, tmp_path, config=None, **state):
        self.state = S(**state)
        self.log = tmp_path / "iterate-log.md"
        self.config = config
        self.term = None

    def tick(self, head, ordinal, tally):
        st, term, _ = tick(self.state, head_sha=head, pr_url=PR, tally=tally, review_base=None,
                           config=self.config, now=NOW, ordinal=ordinal,
                           class_log_path=self.log)
        self.state, self.term = st, term
        return st

    def step(self, head, ordinal, tally):
        st = self.tick(head, ordinal, tally)
        degraded_only = tally["blocking"] == 0 and tally["degraded"] > 0
        if degraded_only:
            action = "degraded"
        elif self.term is None and tally["blocking"] > 0:
            action = "fix"
        else:
            action = "noop"
        self.state = {**st, "budget_last_head": head, "budget_last_round": ordinal,
                      "budget_last_action": action}
        return self.state

    @property
    def lines(self):
        if not self.log.exists():
            return []
        return [ln for ln in self.log.read_text(encoding="utf-8").splitlines()
                if ln.startswith("[tp-pr-iterate] round ")]

    def at(self):
        return self.state["iteration"], self.state[K_KEY]


def test_k_counter_three_cases(tmp_path):  # [Q4]
    # +1: counted round with blocking.
    lp = Loop(tmp_path, iteration=1, budget_last_head="h1", budget_last_round="r1",
              budget_last_action="fix", **{K_KEY: 1})
    assert lp.tick("h2", "r2", BLOCK)[K_KEY] == 2
    # +1: completion with blocking, head not yet blocking.
    lp = Loop(tmp_path, iteration=1, budget_last_head="h1", budget_last_round="r1",
              budget_last_action="noop", budget_head_blocking=False, **{K_KEY: 1})
    assert lp.tick("h1", "r2", BLOCK)[K_KEY] == 2
    # unchanged: degraded-only (counted).
    lp = Loop(tmp_path, iteration=1, budget_last_head="h1", **{K_KEY: 2})
    assert lp.tick("h2", "r2", DEGR)[K_KEY] == 2
    # unchanged: completion with blocking when the head already blocked.
    lp = Loop(tmp_path, iteration=1, budget_last_head="h1", budget_last_round="r1",
              budget_last_action="noop", budget_head_blocking=True, **{K_KEY: 2})
    assert lp.tick("h1", "r2", BLOCK)[K_KEY] == 2
    # 0: counted clean; 0: completion clean.
    lp = Loop(tmp_path, iteration=1, budget_last_head="h1", **{K_KEY: 2})
    assert lp.tick("h2", "r2", CLEAN)[K_KEY] == 0
    lp = Loop(tmp_path, iteration=1, budget_last_head="h1", budget_last_round="r1",
              budget_last_action="degraded", **{K_KEY: 2})
    assert lp.tick("h1", "r2", CLEAN)[K_KEY] == 0


def test_counted_vs_completion_vs_reshell(tmp_path):
    base = dict(iteration=2, budget_last_head="h1", budget_last_round="r2")
    # new head → counted
    lp = Loop(tmp_path, budget_last_action="noop", **base)
    assert lp.tick("h2", "r3", CLEAN)["iteration"] == 3 and len(lp.lines) == 1
    # same head, new ordinal, after degraded/noop → completion (class line written)
    for last in ("degraded", "noop"):
        lp = Loop(tmp_path / last, budget_last_action=last, **base)
        (tmp_path / last).mkdir()
        assert lp.tick("h1", "r3", CLEAN)["iteration"] == 2 and len(lp.lines) == 1
    # same head + same ordinal, or ordinal None → re-shell (nothing counted or logged)
    for i, ordinal in enumerate(("r2", None)):
        d = tmp_path / f"re{i}"
        d.mkdir()
        lp = Loop(d, budget_last_action="noop", **{**base, K_KEY: 1})
        st = lp.tick("h1", ordinal, BLOCK)
        assert st["iteration"] == 2 and st[K_KEY] == 1 and lp.lines == []
    # new ordinal after a fix on the same head → counted
    d = tmp_path / "fix"
    d.mkdir()
    lp = Loop(d, budget_last_action="fix", **base)
    assert lp.tick("h1", "r3", CLEAN)["iteration"] == 3


@pytest.mark.parametrize("last", ["degraded", "noop"])
def test_degraded_only_new_ordinal_same_head(tmp_path, last):  # [Q4]
    lp = Loop(tmp_path, iteration=3, budget_last_head="h1", budget_last_round="r3",
              budget_last_action=last, budget_head_blocking=True, **{K_KEY: 2})
    st = lp.step("h1", "r3.1", DEGR)
    assert (st["iteration"], st[K_KEY], st["budget_head_blocking"]) == (3, 2, True)
    assert lp.lines == []
    assert st["budget_last_action"] == "degraded" and st["budget_last_round"] == "r3.1"


def test_degraded_new_head_is_counted(tmp_path):
    lp = Loop(tmp_path, iteration=1, budget_last_head="h1", **{K_KEY: 1})
    st = lp.step("h2", "r2", DEGR)
    assert (st["iteration"], st[K_KEY]) == (2, 1) and lp.lines == []


def test_head_blocking_reset_on_every_counted_round(tmp_path):  # [Q2]
    lp = Loop(tmp_path, iteration=1, budget_last_head="h1", budget_last_round="r1",
              budget_last_action="fix", budget_head_blocking=True, **{K_KEY: 1})
    assert lp.tick("h2", "r2", DEGR)["budget_head_blocking"] is False


def test_degraded_then_blocking_pairs_three_heads_reach_k(tmp_path):  # [Q2]
    lp = Loop(tmp_path)
    lp.step("H1", "r1", DEGR)
    assert lp.at() == (1, 0)
    lp.step("H1", "r1.1", BLOCK)
    assert lp.at() == (1, 1)
    lp.step("H2", "r2", DEGR)
    assert lp.at() == (2, 1) and lp.state["budget_head_blocking"] is False
    lp.step("H2", "r2.1", BLOCK)
    assert lp.at() == (2, 2)  # without the Q2 reset this stays 1
    lp.step("H3", "r3", DEGR)
    assert lp.at() == (3, 2)
    lp.step("H3", "r3.1", BLOCK)
    assert lp.at() == (3, 3)
    assert lp.term == "convergence-failure"
    assert lp.state["termination_reason"] == "k-consecutive"
    assert len(lp.lines) == 3


def test_k_sequence_with_clean_non_converged_completion(tmp_path):  # [Q4]
    lp = Loop(tmp_path, config={"pdw": {"guards": {"k_consecutive": 3, "round_cap": 6}}})
    expect = [("H1", "r1", BLOCK, 1, 1), ("H2", "r2", BLOCK, 2, 2), ("H3", "r3", CLEAN, 3, 0),
              ("H3", "r4", BLOCK, 3, 1), ("H4", "r5", BLOCK, 4, 2), ("H5", "r6", BLOCK, 5, 3)]
    for n, (head, ordinal, tally, it, k) in enumerate(expect, start=1):
        lp.step(head, ordinal, tally)
        assert lp.at() == (it, k), (head, ordinal)
        assert len(lp.lines) == n
        if n == 4:
            assert lp.state["budget_last_action"] == "fix"
    assert lp.state["termination_reason"] == "k-consecutive"


def test_rereview_after_noop_bumps_k_once(tmp_path):
    lp = Loop(tmp_path)
    lp.step("H1", "r1", BLOCK)
    assert lp.at() == (1, 1)
    lp.state["budget_last_action"] = "noop"  # a re-review after a lifted terminal
    lp.step("H1", "r2", BLOCK)
    assert lp.at() == (1, 1)


def test_new_ordinal_after_fix_same_head_is_counted(tmp_path):
    lp = Loop(tmp_path)
    lp.step("H1", "r1", BLOCK)
    assert lp.state["budget_last_action"] == "fix"
    lp.step("H1", "r2", BLOCK)
    assert lp.at() == (2, 2)
    assert lp.state["budget_head_blocking"] is True


def test_k_bumped_on_round_cap_round(tmp_path):
    lp = Loop(tmp_path, iteration=5, budget_last_head="h5", budget_last_round="r5",
              budget_last_action="fix", **{K_KEY: 0})
    st = lp.tick("h6", "r6", BLOCK)
    assert st["iteration"] == 6 and st[K_KEY] == 1
    assert lp.term == "budget-exhausted" and st["termination_reason"] == "round-cap"


def test_class_line_once_across_reshell(tmp_path):  # Behavior 10
    lp = Loop(tmp_path)
    lp.step("H1", "r1", BLOCK)
    lp.tick("H1", "r1", BLOCK)  # converge retry inside the same round
    lp.tick("H1", None, BLOCK)
    assert lp.lines == ["[tp-pr-iterate] round 1 head=H1 P0 X0 T0 C1 blocking=1"]
    assert lp.at() == (1, 1)


def test_counter_lifecycle_reasserted(tmp_path):
    """Characterization of the deleted loop counter-lifecycle test (Task 3.1).

    Two blocking codereview rounds bump the k-counter 0→1→2; an empty round resets it
    to 0; `consecutive_structural_rounds` (Copilot/threads) is never touched by tick.
    """
    lp = Loop(tmp_path, consecutive_structural_rounds=4)
    lp.step("sha1", "r1", BLOCK)
    assert lp.at() == (1, 1)
    lp.step("sha2", "r2", BLOCK)
    assert lp.at() == (2, 2)
    lp.step("sha3", "r3", CLEAN)
    assert lp.at() == (3, 0)
    assert lp.state["consecutive_structural_rounds"] == 4
    assert lp.term is None
