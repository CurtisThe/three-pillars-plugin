"""Tests for round_budget — limits, the test/code split, git_numstat, checks 1–3.

design: iterate-convergence-budget (Tasks 2.1, 2.2)

`now` and `numstat_fn` are injected; the only git here is `git_numstat`'s argv,
driven through an injected `run_git`.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import round_budget  # noqa: E402
from round_budget import DEFAULTS, BudgetError, git_numstat, limits, split, tick  # noqa: E402


# ---------- limits ----------


def test_limits_none_is_defaults():
    assert limits(None) == DEFAULTS
    assert limits({}) == DEFAULTS


def test_limits_defaults_values():
    assert DEFAULTS == {"round_cap": 3, "growth_multiplier": 1.5, "test_code_ratio": 3.0,
                        "ratio_floor_lines": 100, "growth_floor_lines": 300,
                        "k_consecutive": 3, "wall_clock_sec": 14400}


def test_limits_config_overlays():
    got = limits({"pdw": {"guards": {"round_cap": 7, "wall_clock_sec": 60}}})
    assert got["round_cap"] == 7
    assert got["wall_clock_sec"] == 60
    assert got["k_consecutive"] == 3


def test_limits_ignores_unrelated_and_bad_values():
    got = limits({"pdw": {"guards": {"diff_growth_multiplier": 9, "round_cap": "x",
                                     "k_consecutive": True}}})
    assert got == DEFAULTS


def test_limits_state_max_fields_never_read():
    # limits() takes config only; a state's max_* fields have no path in.
    state_like = {"max_iterations": 2, "max_wall_clock_sec": 1}
    assert limits(state_like) == DEFAULTS


def test_limits_returns_fresh_copy():
    got = limits(None)
    got["round_cap"] = 99
    assert DEFAULTS["round_cap"] == 3


# ---------- split ----------


@pytest.mark.parametrize("path", [
    "pkg/test_mod.py", "mod_test.py", "web/app.test.ts", "web/app.spec.js",
    "tests/helpers.py", "a/test/fixture.json", "src/tests/deep/x.txt",
])
def test_split_test_globs(path):
    got = split([(path, 5, 2)])
    assert got == {"total": 7, "test_added": 5, "code_added": 0}


@pytest.mark.parametrize("path", [
    "pkg/mod.py", "testing/mod.py", "contest.py", "src/latest_x.py", "attest/mod.py",
])
def test_split_code_paths(path):
    got = split([(path, 5, 2)])
    assert got == {"total": 7, "test_added": 0, "code_added": 5}


def test_split_excludes_three_pillars_docs():
    got = split([("three-pillars-docs/tp-designs/x/decisions.md", 400, 10),
                 ("three-pillars-docs/known_issues.md", 3, 3),
                 ("src/a.py", 1, 0)])
    assert got == {"total": 1, "test_added": 0, "code_added": 1}


def test_split_binary_counts_zero():
    got = split([("img.png", "-", "-"), ("src/a.py", 2, 1)])
    assert got == {"total": 3, "test_added": 0, "code_added": 2}


def test_split_total_is_added_plus_deleted_ratio_fields_added_only():
    got = split([("src/a.py", 10, 40), ("tests/test_a.py", 5, 300)])
    assert got["total"] == 355
    assert got["test_added"] == 5
    assert got["code_added"] == 10


def test_split_rename_uses_new_path():
    got = split([("src/{old.py => tests/test_new.py}", 4, 0), ("a.py => test_b.py", 1, 0)])
    assert got["test_added"] == 5


def test_split_empty():
    assert split([]) == {"total": 0, "test_added": 0, "code_added": 0}


# ---------- git_numstat ----------


def _fake_git(rc, out="", calls=None):
    def run(args):
        if calls is not None:
            calls.append(args)
        return rc, out, "boom" if rc else ""
    return run


def test_git_numstat_argv_three_dot_with_cwd():
    calls = []
    git_numstat("BASE", "HEAD1", run_git=_fake_git(0, "", calls), cwd="/w/t")
    assert calls == [["git", "-C", "/w/t", "diff", "--numstat", "-z", "BASE...HEAD1"]]


def test_git_numstat_default_cwd_is_dot():
    calls = []
    git_numstat("b", "h", run_git=_fake_git(0, "", calls))
    assert calls[0][:3] == ["git", "-C", "."]


def test_git_numstat_parses_rows_and_binary():
    out = ("3\t1\tsrc/a.py\0-\t-\timg.png\0" "2\t2\t\0old/x.py\0new/x.py\0"
           "10\t0\ttests/test_a.py\0")
    got = git_numstat("b", "h", run_git=_fake_git(0, out))
    assert got == [("src/a.py", 3, 1), ("img.png", 0, 0), ("new/x.py", 2, 2),
                   ("tests/test_a.py", 10, 0)]


def test_git_numstat_raises_on_failure():
    with pytest.raises(BudgetError):
        git_numstat("b", "h", run_git=_fake_git(128))


def test_git_numstat_raises_on_oserror():
    def boom(args):
        raise OSError("no git")
    with pytest.raises(BudgetError):
        git_numstat("b", "h", run_git=boom)


def test_git_numstat_default_runner_is_review_proof():
    import review_proof
    assert round_budget._default_run_git is review_proof._default_run_git


# ---------- tick: PR key, started_at, wall clock, round cap (checks 1–3) ----------

NOW = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)
PR = "https://github.com/o/r/pull/7"
BUDGET_FIELDS = ("budget_pr_url", "budget_baseline_head", "budget_baseline_split",
                 "budget_last_head", "budget_last_round", "budget_last_action",
                 "budget_head_blocking")


def T(blocking=0, degraded=0):
    return {"P": 0, "X": 0, "T": 0, "C": 0, "blocking": blocking, "degraded": degraded}


def S(**kw):
    base = {"phase": "awaiting-review", "iteration": 0, "started_at": NOW.isoformat(),
            "consecutive_codereview_structural_rounds": 0, "budget_pr_url": PR,
            "budget_last_head": None, "budget_last_round": None, "budget_last_action": None}
    base.update(kw)
    return base


def run(state, head="h1", tally=None, pr_url=PR, ordinal="r1", config=None, now=NOW, **kw):
    return tick(state, head_sha=head, pr_url=pr_url, tally=tally or T(), review_base=None,
                config=config, now=now, ordinal=ordinal, **kw)


def test_pr_key_reset_clears_counters_and_budget_fields():
    dirty = {f: "x" for f in BUDGET_FIELDS}
    state = S(iteration=5, original_diff_lines=900, started_at="2020-01-01T00:00:00+00:00",
              consecutive_codereview_structural_rounds=2, **dirty)
    st, term, _ = run(state, pr_url="https://github.com/o/r/pull/8", head="z")
    assert term is None
    assert st["iteration"] == 1  # reset to 0, then this new head counts
    assert st["started_at"] == NOW.isoformat()
    assert st["original_diff_lines"] is None
    assert st["consecutive_codereview_structural_rounds"] == 0
    assert st["budget_pr_url"] == "https://github.com/o/r/pull/8"
    for f in BUDGET_FIELDS[1:]:
        assert st[f] in (None, False), f


def test_pr_key_reset_clears_budget_terminal_phase():
    state = S(iteration=6, phase="budget-exhausted", termination_reason="round-cap")
    st, term, _ = run(state, pr_url="https://github.com/o/r/pull/8", tally=T(blocking=1))
    assert term is None
    assert st["phase"] == "awaiting-review"
    assert st["termination_reason"] is None


def test_pr_key_reset_not_triggered_on_first_sight_or_same_pr():
    st, _, _ = run(S(iteration=3, budget_pr_url=None), head="h9")
    assert st["iteration"] == 4 and st["budget_pr_url"] == PR
    st, _, _ = run(S(iteration=3), head="h9")
    assert st["iteration"] == 4


def test_started_at_missing_set_to_now():
    state = S()
    del state["started_at"]
    st, term, _ = run(state)
    assert term is None and st["started_at"] == NOW.isoformat()


@pytest.mark.parametrize("bad", ["yesterday", "2026-09-24T10:00:00", 12345])
def test_started_at_unparseable_or_naive_is_budget_error(bad):
    st, term, detail = run(S(started_at=bad))
    assert term == "budget-exhausted"
    assert st["termination_reason"] == "budget-error"
    assert detail["signal"] == "budget-error"


def test_started_at_z_suffix_accepted():
    _, term, _ = run(S(started_at="2026-09-24T11:00:00Z"))
    assert term is None


def test_wall_clock():
    st, term, detail = run(S(budget_active_elapsed_sec=14401))
    assert term == "cap-exhausted"
    assert st["termination_reason"] == "wall-clock"
    assert detail["signal"] == "wall-clock" and detail["limit"] == 14400
    _, term, _ = run(S(budget_active_elapsed_sec=14400))
    assert term is None


def test_round_cap_blocking_at_cap_fires():
    st, term, detail = run(S(iteration=2, budget_last_head="h2"), head="h3", tally=T(blocking=1))
    assert st["iteration"] == 3
    assert term == "budget-exhausted" and st["termination_reason"] == "round-cap"
    assert detail == {**detail, "iteration": 3, "round_cap": 3, "signal": "round-cap",
                      "measured": 3, "limit": 3}
    assert "round-cap" in detail["holding"]


@pytest.mark.parametrize("tally", [T(), T(degraded=2)])
def test_round_cap_clean_or_degraded_at_cap_no_terminal(tally):
    st, term, detail = run(S(iteration=5, budget_last_head="h5"), head="h6", tally=tally)
    assert st["iteration"] == 6 and term is None
    assert detail["signal"] is None and detail["holding"] == []


def test_round_cap_below_cap_blocking_no_terminal():
    st, term, _ = run(S(iteration=1, budget_last_head="h1"), head="h2", tally=T(blocking=2))
    assert st["iteration"] == 2 and term is None


def test_round_cap_from_config():
    cfg = {"pdw": {"guards": {"round_cap": 7}}}
    _, term, _ = run(S(iteration=5, budget_last_head="h5"), head="h6", tally=T(blocking=1),
                     config=cfg)
    assert term is None


# Every round kind: (last_head, last_round, last_action, head, ordinal).
_KINDS = [
    ("h1", "r1", "fix", "h2", "r2"),        # counted: new head
    ("h1", "r1", "fix", "h1", "r2"),        # counted: new ordinal after a fix
    ("h1", "r1", "noop", "h1", "r2"),       # completion
    ("h1", "r1", "degraded", "h1", "r2"),   # completion after a degraded round
    ("h1", "r1", "noop", "h1", "r1"),       # re-shell: same ordinal
    ("h1", "r1", "noop", "h1", None),       # re-shell: no ordinal
    ("h1", "r1", "noop", "merge", "r2"),    # non-fix head (merge from main)
]


@pytest.mark.parametrize("iteration", [5, 6, 7, 9])
@pytest.mark.parametrize("kind", _KINDS)
@pytest.mark.parametrize("tally", [T(blocking=1), T(blocking=1, degraded=1), T(), T(degraded=1)])
def test_no_fix_at_or_past_cap(iteration, kind, tally):
    last_head, last_round, last_action, head, ordinal = kind
    state = S(iteration=iteration, budget_last_head=last_head, budget_last_round=last_round,
              budget_last_action=last_action)
    st, term, _ = run(state, head=head, ordinal=ordinal, tally=tally)
    if st["iteration"] >= 6 and tally["blocking"] > 0:
        assert term is not None  # Behavior 5: no fix dispatched at/after the cap
    if tally["blocking"] == 0:
        assert term is None  # the cap never stops a verify round
