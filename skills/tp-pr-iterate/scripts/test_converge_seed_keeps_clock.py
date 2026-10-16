"""A converge seed round keeps the active-clock fields (the `budget_` prefix rule).

design: fable-first-stops (Task 1.1). `converge._seed_state` re-seeds the state on
every clean round; if it dropped `budget_active_elapsed_sec` / `budget_round_started_at`
the active clock would restart every clean round.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import converge  # noqa: E402

NOW = "2026-09-24T12:00:00+00:00"
CLOCK = {"budget_active_elapsed_sec": 1234.5,
         "budget_round_started_at": "2026-09-24T11:50:00+00:00"}


def _prior(path: Path, **kw) -> None:
    st = {"phase": "awaiting-review", "iteration": 3, "max_iterations": 8,
          "max_wall_clock_sec": 14400, "started_at": "2026-09-24T10:00:00+00:00",
          "transitions": [], "original_diff_lines": 250,
          "budget_pr_url": "https://github.com/o/r/pull/1", **CLOCK}
    st.update(kw)
    path.write_text(json.dumps(st), encoding="utf-8")


def test_seed_keeps_both_clock_fields(tmp_path):
    path = tmp_path / "state.json"
    _prior(path)
    converge._seed_state(path, "h4", now_iso=NOW)
    s = json.loads(path.read_text(encoding="utf-8"))
    assert {k: s[k] for k in CLOCK} == CLOCK
    assert s["started_at"] == "2026-09-24T10:00:00+00:00"


def test_seed_keeps_clock_on_a_budget_terminal(tmp_path):
    path = tmp_path / "state.json"
    _prior(path, phase="cap-exhausted", termination_reason="wall-clock")
    converge._seed_state(path, "h4", now_iso=NOW)
    s = json.loads(path.read_text(encoding="utf-8"))
    assert {k: s[k] for k in CLOCK} == CLOCK
    assert (s["phase"], s["termination_reason"]) == ("cap-exhausted", "wall-clock")


def test_seed_of_an_absent_state_carries_no_clock(tmp_path):
    path = tmp_path / "state.json"
    converge._seed_state(path, "h4", now_iso=NOW)
    s = json.loads(path.read_text(encoding="utf-8"))
    assert "budget_active_elapsed_sec" not in s and "budget_round_started_at" not in s
