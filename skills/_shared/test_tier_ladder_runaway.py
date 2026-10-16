"""test_tier_ladder_runaway.py — the ``runaway`` rows of the ladder table.

design: run-throughput (detailed-design-runaway.md §Failure class, ladder and verdict;
detailed-design-runaway-check.md §Tests)

A runaway on a local rung goes to ``quality_next`` with no same-rung retry, whatever
``max_retries`` is; escalate off blocks it. It counts as an attempt (it ran). An
``orphan-holds-gpu`` ``unavailable`` moves a fresh ``local-medium`` row to ``sonnet-medium``
with no attempt counted. The verdict carries the class, the fingerprint and ``stuck``.
"""
from __future__ import annotations

import tier_ladder
from local_implement_config import DEFAULTS

CFG = {**DEFAULTS, "max_retries": 2}
GEN = "runaway: generation client-reset mid-response"
WALL = "runaway: wall-clock 1200s ≥ 1200s"


def _rec(rung: str) -> dict:
    return {"task_id": "2.2", "tier_path": [rung], "attempts": {rung: 0}, "escalated": False,
            "final": None, "verdicts": [], "tokens": None, "route": "routed/ok"}


def test_local_medium_runaway_escalates_without_retry():
    action, nxt, out = tier_ladder.next_step(_rec("local-medium"), "FAIL", CFG, reason=GEN)
    assert (action, nxt) == ("escalate", "local-xhigh")
    assert out["attempts"] == {"local-medium": 1, "local-xhigh": 0}


def test_local_xhigh_runaway_goes_to_sonnet_xhigh():
    action, nxt, _out = tier_ladder.next_step(_rec("local-xhigh"), "FAIL", CFG, reason=WALL)
    assert (action, nxt) == ("escalate", "sonnet-xhigh")


def test_runaway_escalate_off_blocks():
    action, nxt, out = tier_ladder.next_step(
        _rec("local-medium"), "FAIL", {**CFG, "escalate": False}, reason=GEN)
    assert (action, nxt, out["final"]) == ("blocked", None, "blocked")
    assert out["verdicts"][-1]["stuck"] == "runaway"


def test_orphan_holds_gpu_is_unavailable_no_attempt():
    action, nxt, out = tier_ladder.next_step(
        _rec("local-medium"), "unavailable", CFG, reason="orphan-holds-gpu")
    assert (action, nxt) == ("escalate", "sonnet-medium")
    assert out["attempts"] == {"local-medium": 0, "sonnet-medium": 0}


def test_runaway_verdict_carries_class_fingerprint_stuck():
    _a, _n, out = tier_ladder.next_step(
        _rec("local-medium"), "FAIL", CFG, reason=GEN,
        evidence={"gen": {"max": 18357}, "served": {"local_requests": 23}, "wall_s": 661.5})
    v = out["verdicts"][-1]
    assert (v["class"], v["stuck"], v["fingerprint"]) == (
        "runaway", "runaway", "runaway||runaway: generation")
    assert (v["gen"], v["served"], v["wall_s"]) == (
        {"max": 18357}, {"local_requests": 23}, 661.5)
    _a, _n, out = tier_ladder.next_step(_rec("local-medium"), "FAIL", CFG, reason=WALL)
    assert out["verdicts"][-1]["fingerprint"] == "runaway||runaway: wall-clock"


def test_runaway_off_the_local_rung_is_quality():
    """No watchdog is armed off a local rung, but the table stays total."""
    action, nxt, out = tier_ladder.next_step(_rec("sonnet-xhigh"), "FAIL", CFG, reason=GEN)
    assert (action, nxt) == ("retry", "sonnet-xhigh")
    assert out["verdicts"][-1]["stuck"] is None
