"""Tests for the active-time wall clock in `round_budget.tick` / `budget_clock`.

design: fable-first-stops (Task 1.1)

The wall clock sums the spans spent inside review rounds (`budget_round_started_at`
stamped at round start, folded into `budget_active_elapsed_sec` at the tick), so a
pause between rounds never trips it. `started_at` stays the loop-start record.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).parent))

import budget_clock  # noqa: E402
from round_budget import BUDGET_FIELDS, tick  # noqa: E402

NOW = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)
PR = "https://github.com/o/r/pull/7"
K = "consecutive_codereview_structural_rounds"
SCHEMA = json.loads((Path(__file__).resolve().parent.parent / "schemas"
                     / "iterate-state.v1.json").read_text(encoding="utf-8"))
TALLY = {"P": 0, "X": 0, "T": 0, "C": 0, "blocking": 0, "degraded": 0}


def S(**kw):
    base = {"phase": "awaiting-review", "iteration": 0, "max_iterations": 6,
            "max_wall_clock_sec": 14400, "started_at": NOW.isoformat(), "transitions": [],
            K: 0, "budget_pr_url": PR, "budget_last_head": None,
            "budget_last_round": None, "budget_last_action": None}
    base.update(kw)
    return base


def run(state, *, config=None, pr_url=PR, head="h1", ordinal="r1", now=NOW):
    return tick(state, head_sha=head, pr_url=pr_url, tally=TALLY, review_base=None,
                config=config, now=now, ordinal=ordinal)


def valid(state):
    errs = [e.message for e in Draft202012Validator(SCHEMA).iter_errors(state)]
    assert errs == []


def test_pause_between_rounds_never_trips_wall_clock():  # (a)
    state = S(started_at=(NOW - timedelta(hours=30)).isoformat(),
              budget_active_elapsed_sec=0,
              budget_round_started_at=(NOW - timedelta(minutes=10)).isoformat())
    st, term, detail = run(state)
    assert term is None and detail["signal"] is None
    assert st["budget_active_elapsed_sec"] == pytest.approx(600)
    assert st["budget_round_started_at"] is None
    assert st["started_at"] == state["started_at"]  # loop-start record untouched
    valid(st)


def test_summed_spans_over_the_limit_fire_wall_clock():  # (b)
    state = S(budget_active_elapsed_sec=14000,
              budget_round_started_at=(NOW - timedelta(minutes=10)).isoformat())
    st, term, detail = run(state)
    assert term == "cap-exhausted" and st["phase"] == "cap-exhausted"
    assert st["termination_reason"] == "wall-clock"
    assert detail["signal"] == "wall-clock" and detail["limit"] == 14400
    assert detail["measured"] == pytest.approx(14600)
    valid(st)


def test_span_exactly_at_the_limit_does_not_fire():
    state = S(budget_active_elapsed_sec=13800,
              budget_round_started_at=(NOW - timedelta(seconds=600)).isoformat())
    _, term, _ = run(state)
    assert term is None


def test_legacy_state_starts_active_time_at_zero():  # (c)
    state = S(started_at=(NOW - timedelta(hours=30)).isoformat())
    assert "budget_active_elapsed_sec" not in state
    st, term, detail = run(state)
    assert term is None and detail["signal"] != "budget-error"
    assert st["budget_active_elapsed_sec"] == 0 and st["budget_round_started_at"] is None
    valid(st)


def test_none_total_reads_as_zero():  # (c)
    st, term, _ = run(S(budget_active_elapsed_sec=None))
    assert term is None and st["budget_active_elapsed_sec"] == 0
    assert budget_clock.active_elapsed({"budget_active_elapsed_sec": None}, NOW)[0] == 0


def test_retick_without_a_fresh_round_start_adds_nothing():  # (d)
    state = S(budget_active_elapsed_sec=100,
              budget_round_started_at=(NOW - timedelta(seconds=50)).isoformat())
    first, _, _ = run(state)
    assert first["budget_active_elapsed_sec"] == pytest.approx(150)
    second, term, _ = run(first, now=NOW + timedelta(hours=9), ordinal="r2")
    assert term is None
    assert second["budget_active_elapsed_sec"] == pytest.approx(150)
    assert second["budget_round_started_at"] is None


@pytest.mark.parametrize("bad", ["yesterday", "2026-09-24T11:00:00", 12345, ""])
def test_unparseable_or_naive_round_start_adds_nothing_and_is_cleared(bad):
    st, term, _ = run(S(budget_active_elapsed_sec=40, budget_round_started_at=bad))
    assert term is None
    assert st["budget_active_elapsed_sec"] == 40 and st["budget_round_started_at"] is None


def test_z_suffix_round_start_is_accepted():
    st, _, _ = run(S(budget_round_started_at="2026-09-24T11:50:00Z"))
    assert st["budget_active_elapsed_sec"] == pytest.approx(600)


def test_future_round_start_is_clamped_to_zero():
    st, _, _ = run(S(budget_round_started_at=(NOW + timedelta(hours=1)).isoformat()))
    assert st["budget_active_elapsed_sec"] == 0


@pytest.mark.parametrize("bad", [-5, "12", True, [1]])
def test_garbage_total_reads_as_zero(bad):
    assert budget_clock.active_elapsed({"budget_active_elapsed_sec": bad}, NOW)[0] == 0


def test_sticky_wall_clock_lifts_when_active_total_is_under_a_raised_limit():  # (e)
    state = S(phase="cap-exhausted", termination_reason="wall-clock",
              budget_active_elapsed_sec=15000)
    st, term, detail = run(state)  # default 14400: still over, holds
    assert term == "cap-exhausted" and detail["measured"] == pytest.approx(15000)
    st, term, _ = run(state, config={"pdw": {"guards": {"wall_clock_sec": 20000}}})
    assert term is None
    assert st["phase"] == "awaiting-review" and st["termination_reason"] is None
    assert any("[budget-lifted] wall-clock" in str(t.get("note")) for t in st["transitions"])
    valid(st)


def test_sticky_wall_clock_ignores_a_long_started_at_once_active_time_is_low():
    state = S(phase="cap-exhausted", termination_reason="wall-clock",
              started_at=(NOW - timedelta(hours=30)).isoformat(),
              budget_active_elapsed_sec=100)
    st, term, _ = run(state)
    assert term is None and st["phase"] == "awaiting-review"


def test_pr_key_reset_clears_both_clock_fields():  # (f)
    assert {"budget_active_elapsed_sec", "budget_round_started_at"} <= set(BUDGET_FIELDS)
    state = S(budget_active_elapsed_sec=9000,
              budget_round_started_at=(NOW - timedelta(minutes=5)).isoformat())
    st, term, _ = run(state, pr_url="https://github.com/o/r/pull/8")
    assert term is None
    assert st["budget_active_elapsed_sec"] == 0 and st["budget_round_started_at"] is None
    valid(st)


def test_started_at_still_bootstraps_and_gates_budget_error():
    state = S(budget_active_elapsed_sec=10)
    del state["started_at"]
    st, term, _ = run(state)
    assert term is None and st["started_at"] == NOW.isoformat()
    st, term, detail = run(S(started_at="yesterday"))
    assert term == "budget-exhausted" and detail["signal"] == "budget-error"
    assert st["termination_reason"] == "budget-error"


def test_every_returned_state_validates_against_the_schema():  # (g)
    for state in (S(), S(budget_active_elapsed_sec=None, budget_round_started_at=None),
                  S(budget_active_elapsed_sec=14000.5,
                    budget_round_started_at=(NOW - timedelta(minutes=10)).isoformat())):
        st, _, _ = run(state)
        valid(st)
        assert isinstance(st["budget_active_elapsed_sec"], (int, float))


def test_active_elapsed_returns_total_and_clearing_updates():
    total, updates = budget_clock.active_elapsed(
        {"budget_active_elapsed_sec": 5,
         "budget_round_started_at": (NOW - timedelta(seconds=7)).isoformat()}, NOW)
    assert total == pytest.approx(12)
    assert updates == {"budget_active_elapsed_sec": total, "budget_round_started_at": None}
