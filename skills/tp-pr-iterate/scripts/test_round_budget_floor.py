"""The growth floor: `pdw.guards.growth_floor_lines` gates check 4 (design diff-growth-min-floor).

Task 1.1. Below the floor (default 300 changed lines — the three-dot total, added +
deleted) neither `growth-lines` nor `test-code-ratio` is judged; above it today's
multipliers apply unchanged. `numstat_fn` is injected and every measure is
`review_base...head`, modelled on `test_round_budget_growth.py` (`run`/`baseline`).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from round_budget import K_KEY, limits, tick  # noqa: E402

NOW = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)
PR = "https://github.com/o/r/pull/234"
CLEAN = {"P": 0, "X": 0, "T": 0, "C": 0, "blocking": 0, "degraded": 0}


def floor_cfg(n):
    return {"pdw": {"guards": {"growth_floor_lines": n}}}


def S(**kw):
    base = {"phase": "awaiting-review", "iteration": 0, "started_at": NOW.isoformat(),
            K_KEY: 0, "budget_pr_url": PR, "original_diff_lines": None,
            "budget_baseline_head": None}
    base.update(kw)
    return base


def rows(code=0, test=0):
    return [("src/mod.py", code, 0), ("tests/test_mod.py", test, 0)]


def run(state, head, numstat, base="BASE", config=None):
    fn = (lambda a, b: numstat) if numstat is not None else None
    return tick(state, head_sha=head, pr_url=PR, tally=CLEAN, review_base=base,
                config=config, now=NOW, ordinal=head, numstat_fn=fn)


def baseline(code, test, config=None):
    """R1 over `rows(code, test)` — added only, so the total is code + test."""
    st, term, _ = run(S(original_diff_lines=None), "h1", rows(code=code, test=test),
                      config=config)
    assert term is None
    return {**st, "budget_last_head": "h1", "budget_last_round": "h1"}


# ---------- the floor is a limit ----------


def test_limits_default_floor_is_300():
    assert limits(None)["growth_floor_lines"] == 300
    assert limits({})["growth_floor_lines"] == 300


def test_limits_floor_from_config_including_zero():
    assert limits(floor_cfg(100))["growth_floor_lines"] == 100
    assert limits(floor_cfg(0))["growth_floor_lines"] == 0


# ---------- the seed's guard cases ----------


def test_small_pr_fix_with_tests_is_below_the_floor():
    """PR #234: 61 -> 187 lines with tests. Neither growth nor ratio is judged."""
    st = baseline(code=40, test=21)  # R1 total 61
    st, term, detail = run(st, "h2", rows(code=60, test=127))  # R2 total 187
    assert st["original_diff_lines"] == 61
    assert term is None and detail["holding"] == []


def test_large_pr_growth_fires_as_before():
    """400 -> 1000 lines: above the floor the 1.5x multiplier is unchanged."""
    st = baseline(code=400, test=0)
    _, term, detail = run(st, "h2", rows(code=1000, test=0))
    assert term == "budget-exhausted" and detail["signal"] == "growth-lines"
    assert detail["measured"] == 1000 and detail["limit"] == 600


def test_floor_zero_judges_the_small_diff():
    st = baseline(code=40, test=21, config=floor_cfg(0))
    _, term, detail = run(st, "h2", rows(code=60, test=127), config=floor_cfg(0))
    assert term == "budget-exhausted" and detail["signal"] == "growth-lines"


def test_floor_100_judges_the_same_diff():
    st = baseline(code=40, test=21, config=floor_cfg(100))
    _, term, detail = run(st, "h2", rows(code=60, test=127), config=floor_cfg(100))
    assert term == "budget-exhausted" and detail["signal"] == "growth-lines"


def test_ratio_is_not_judged_below_the_floor():
    """The ratio would fire on 150 added test lines; the floor stops the check."""
    cfg = {"pdw": {"guards": {"growth_multiplier": 10}}}  # growth cannot fire here
    st = baseline(code=100, test=0, config=cfg)
    _, term, detail = run(st, "h2", rows(code=100, test=150), config=cfg)
    assert term is None and detail["holding"] == []


def test_ratio_fires_above_the_floor():
    cfg = {"pdw": {"guards": {"growth_multiplier": 100}}}
    st = baseline(code=1000, test=0)
    _, term, detail = run(st, "h2", rows(code=1010, test=3100), config=cfg)
    assert term == "budget-exhausted" and detail["signal"] == "test-code-ratio"


def test_total_at_the_floor_is_not_judged():
    """The floor is inclusive: a total equal to it is not judged."""
    st = baseline(code=50, test=0, config=floor_cfg(100))
    _, term, _ = run(st, "h2", rows(code=50, test=50), config=floor_cfg(100))
    assert term is None
