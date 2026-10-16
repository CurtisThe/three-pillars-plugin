"""A newly fired budget terminal is handed to the finalizer, not labelled.

design: fable-first-stops (Task 2.2). `loop_driver.run_round` returns a
`finalizer_stop` event when `round_budget.tick` newly fires a budget terminal and
applies NO `tp:needs-human-attention` (that label now comes from the finalizer's
escalate path). A terminal already held from the prior state labels as before, so a
caller that skips the finalizer prose still gets the label.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import loop_driver  # noqa: E402

NOW = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)
PR = "https://github.com/o/r/pull/9"
# keep-the-pin: the growth-lines cases diff 100 lines, below the 300 floor.
CFG = {"review": {"expects_copilot": False}, "ci": {"expects_github_checks": False},
       "pdw": {"guards": {"growth_floor_lines": 0}}}
K = "consecutive_codereview_structural_rounds"
NEEDS_HUMAN = "tp:needs-human-attention"
READY = "tp:ready-for-human-merge"
BLOCKING = {"source": "code-review", "file": "a.py", "line_range": [1, 2], "summary": "bug",
            "verdict": "structural", "class": "P", "blocking": True}
MINOR = dict(BLOCKING, verdict="minor", blocking=False, **{"class": "C"})


def _state(**kw):
    st = {"phase": "awaiting-review", "iteration": 0, "max_iterations": 8,
          "max_wall_clock_sec": 14400, "started_at": NOW.isoformat(), "transitions": [],
          "last_verdict": "minor-only", "budget_pr_url": PR}
    st.update(kw)
    return st


def _big_numstat(_base, _head):
    return [("src/a.py", 100, 0)]


# signal -> (terminal phase, prior state, findings, extra run_round kwargs); each fires
# on the first round from a non-terminal state.
CASES = {
    "wall-clock": ("cap-exhausted", {"budget_active_elapsed_sec": 5 * 3600}, [], {}),
    "round-cap": ("budget-exhausted",
                  {"iteration": 5, "budget_last_head": "h5", "budget_last_round": "r5",
                   "budget_last_action": "fix"}, [BLOCKING], {}),
    "k-consecutive": ("convergence-failure",
                      {"iteration": 1, K: 2, "budget_last_head": "h5",  # k fires below cap 3
                       "budget_last_round": "r5", "budget_last_action": "fix"},
                      [BLOCKING], {}),
    "growth-lines": ("budget-exhausted",
                     {"budget_baseline_head": "h0", "original_diff_lines": 10,
                      "budget_baseline_split": {"test_added": 0, "code_added": 0}},
                     [], {"review_base": "base1", "numstat_fn": _big_numstat}),
    "budget-error": ("budget-exhausted", {"started_at": "not-a-date"}, [], {}),
}


def _round(state, findings, labels, **kw):
    return loop_driver.run_round(
        state, head_sha="h6", codereview_findings=findings, reviewed=None,
        unresolved_actionable=0, ci_rollup=[], config=CFG, now=NOW, pr_url=PR,
        proof_ok=True, ordinal="r6",
        label_fn=lambda _u, lbl: labels.append(("+", lbl)),
        unlabel_fn=lambda _u, lbl: labels.append(("-", lbl)), **kw)


@pytest.mark.parametrize("signal", sorted(CASES))
def test_newly_fired_budget_terminal_hands_the_finalizer_the_stop(signal):
    phase, prior, findings, kw = CASES[signal]
    labels = []
    out = _round(_state(**prior), findings, labels, **kw)
    assert out["terminal"] == phase and out["action"] == "noop"
    assert out["state"]["termination_reason"] == signal
    assert out["budget"]["signal"] == signal
    assert out["finalizer_stop"] == {
        "source": "pr-iterate", "signal": signal, "target": PR, "head": "h6",
        "detail": out["budget"]}
    assert ("+", NEEDS_HUMAN) not in labels
    assert ("-", READY) in labels


@pytest.mark.parametrize("signal", sorted(CASES))
def test_terminal_held_from_the_prior_state_labels_as_before(signal):
    phase, prior, findings, kw = CASES[signal]
    fired = _round(_state(**prior), findings, [], **kw)
    assert "finalizer_stop" in fired  # the first round handed the stop over
    labels = []
    held = _round(fired["state"], findings, labels, **kw)  # escalated or skipped: held
    assert held["terminal"] == phase and held["state"]["termination_reason"] == signal
    assert "finalizer_stop" not in held
    assert ("+", NEEDS_HUMAN) in labels
    assert ("-", READY) in labels


def test_a_different_held_signal_does_not_suppress_the_new_stop():
    """A held terminal labels only when it is the SAME reason the tick reports."""
    st = _state(phase="cap-exhausted", termination_reason="wall-clock", iteration=5,
                budget_active_elapsed_sec=0, budget_last_head="h5",
                budget_last_round="r5", budget_last_action="fix")
    labels = []
    out = _round(st, [BLOCKING], labels)  # wall-clock lifted, round-cap fires fresh
    assert out["state"]["termination_reason"] == "round-cap"
    assert out["finalizer_stop"]["signal"] == "round-cap"
    assert ("+", NEEDS_HUMAN) not in labels


def test_non_budget_terminal_carries_no_finalizer_stop():
    labels = []
    out = _round(_state(), [MINOR], labels)
    assert out["terminal"] == "two-stable [code-review-only]"
    assert "finalizer_stop" not in out
    assert ("+", READY) in labels


def test_non_terminal_round_carries_no_finalizer_stop():
    out = _round(_state(), [BLOCKING], [])
    assert out["terminal"] is None and out["action"] == "fix"
    assert "finalizer_stop" not in out
