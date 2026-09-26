"""Tests for round_budget growth + ratio (check 4) and the R1 baseline.

design: iterate-convergence-budget (Tasks 2.4, 2.6)

`numstat_fn(base, head)` is injected; every measure is `review_base...head`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import iterate_state  # noqa: E402
from round_budget import K_KEY, BudgetError, git_numstat, loop_delta, tick  # noqa: E402

NOW = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)
PR = "https://github.com/o/r/pull/7"
CLEAN = {"P": 0, "X": 0, "T": 0, "C": 0, "blocking": 0, "degraded": 0}


def S(**kw):
    base = {"phase": "awaiting-review", "iteration": 0, "started_at": NOW.isoformat(),
            K_KEY: 0, "budget_pr_url": PR, "original_diff_lines": None,
            "budget_baseline_head": None}
    base.update(kw)
    return base


def rows(code=0, test=0, deleted_code=0, deleted_test=0):
    return [("src/mod.py", code, deleted_code), ("tests/test_mod.py", test, deleted_test)]


def run(state, head, numstat, base="BASE", config=None):
    fn = (lambda a, b: numstat) if numstat is not None else None
    return tick(state, head_sha=head, pr_url=PR, tally=CLEAN, review_base=base,
                config=config, now=NOW, ordinal=head, numstat_fn=fn)


def baseline(code=100, test=100):
    st, term, _ = run(S(original_diff_lines=100), "h1", rows(code=code, test=test))
    assert term is None
    return {**st, "budget_last_head": "h1", "budget_last_round": "h1"}


def test_r1_baseline_overwrites_seeded_original():
    st = baseline(code=300, test=100)
    assert st["original_diff_lines"] == 400
    assert st["budget_baseline_head"] == "h1"
    assert st["budget_baseline_split"] == {"test_added": 100, "code_added": 300}


def test_baseline_not_recaptured_on_later_rounds():
    st, term, _ = run(baseline(), "h2", rows(code=110, test=100))
    assert term is None
    assert st["original_diff_lines"] == 200 and st["budget_baseline_head"] == "h1"


def test_baseline_survives_iterate_state_reload(tmp_path):
    path = tmp_path / "iterate-state.7.v1.json"
    iterate_state.write_state_atomic(path, baseline())
    reloaded, boot = iterate_state.load_or_bootstrap(path)
    assert boot is False
    st, term, detail = run(reloaded, "h2", rows(code=201, test=100))
    assert st["original_diff_lines"] == 200
    assert term == "budget-exhausted" and st["termination_reason"] == "growth-lines"
    assert detail["measured"] == 301 and detail["limit"] == 300


def test_growth_at_multiplier_is_fine():
    _, term, _ = run(baseline(), "h2", rows(code=200, test=100))
    assert term is None


def test_growth_counts_deleted_lines():
    _, term, detail = run(baseline(), "h2", rows(code=100, test=100, deleted_code=101))
    assert detail["signal"] == "growth-lines" and term == "budget-exhausted"


def test_growth_multiplier_from_config():
    cfg = {"pdw": {"guards": {"growth_multiplier": 3}}}
    _, term, _ = run(baseline(), "h2", rows(code=300, test=100), config=cfg)
    assert term is None


def test_test_code_ratio_fires_over_floor():
    base = baseline(code=1000, test=0)  # original 1000 → growth limit 1500
    st, term, detail = run(base, "h2", rows(code=1010, test=120))
    assert term == "budget-exhausted" and st["termination_reason"] == "test-code-ratio"
    assert detail["measured"] == 120 and detail["limit"] == 30


def test_test_code_ratio_below_floor_is_fine():
    _, term, _ = run(baseline(code=1000, test=0), "h2", rows(code=1010, test=99))
    assert term is None


def test_ratio_uses_added_lines_only():
    # a large test-file deletion never trips the ratio
    _, term, _ = run(baseline(code=1000, test=300), "h2",
                     rows(code=1000, test=300, deleted_test=400))
    assert term is None


def test_loop_delta_clamped_non_negative():
    d = loop_delta({"test_added": 50, "code_added": 80}, {"test_added": 10, "code_added": 30})
    assert d == {"test_added": 0, "code_added": 0}
    d = loop_delta({"test_added": 10, "code_added": 80}, {"test_added": 60, "code_added": 20})
    assert d == {"test_added": 50, "code_added": 0}


def test_growth_skipped_without_numstat_or_base():
    st, term, _ = run(S(original_diff_lines=100), "h1", None)
    assert term is None and st["budget_baseline_head"] is None
    st, term, _ = run(S(original_diff_lines=100), "h1", rows(code=900), base=None)
    assert term is None and st["budget_baseline_head"] is None
    assert st["original_diff_lines"] == 100


def test_numstat_error_is_budget_error():
    def boom(a, b):
        raise BudgetError("bad base")
    st, term, detail = tick(S(), head_sha="h1", pr_url=PR, tally=CLEAN, review_base="BASE",
                            config=None, now=NOW, ordinal="r1", numstat_fn=boom)
    assert term == "budget-exhausted" and st["termination_reason"] == "budget-error"
    assert detail["signal"] == "budget-error"


def test_numstat_called_three_dot_args():
    calls = []

    def fn(a, b):
        calls.append((a, b))
        return rows(code=1)
    tick(S(), head_sha="h1", pr_url=PR, tally=CLEAN, review_base="BASE", config=None,
         now=NOW, ordinal="r1", numstat_fn=fn)
    assert calls == [("BASE", "h1")]


# ---------- Task 2.6: temp-repo numstat, merge from main (characterization) ----------

_GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_NOSYSTEM": "1", "HOME": "/nonexistent"}


def _git(repo, *args):
    env = {**os.environ, **_GIT_ENV}
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                         env=env, check=True)
    return out.stdout.strip()


def _write(repo, rel, n):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(f"line {i}\n" for i in range(n)), encoding="utf-8")


def _commit(repo, msg):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


def _merge_from_main_repo(tmp_path):
    """main: base → upstream(+500); feature: R1(+100) → merge from main."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _write(repo, "README.md", 1)
    stale_base = _commit(repo, "base")
    _git(repo, "checkout", "-q", "-b", "feature")
    _write(repo, "src/feature.py", 100)
    r1_head = _commit(repo, "feature R1")
    _git(repo, "checkout", "-q", "main")
    _write(repo, "src/upstream.py", 500)
    fresh_base = _commit(repo, "main moves on")
    _git(repo, "checkout", "-q", "feature")
    _git(repo, "merge", "-q", "--no-edit", "main")
    return repo, stale_base, r1_head, fresh_base, _git(repo, "rev-parse", "HEAD")


def _numstat_in(repo):
    return lambda a, b: git_numstat(a, b, cwd=repo)


def _r1(repo, stale_base, r1_head):
    st, term, _ = tick(S(), head_sha=r1_head, pr_url=PR, tally=CLEAN, review_base=stale_base,
                       config=None, now=NOW, ordinal="r1", numstat_fn=_numstat_in(repo))
    assert term is None and st["original_diff_lines"] == 100
    return {**st, "budget_last_head": r1_head, "budget_last_round": "r1",
            "budget_last_action": "noop"}


def test_merge_from_main_refreshed_base_leaves_growth_unchanged(tmp_path):
    repo, stale, r1_head, fresh, merged = _merge_from_main_repo(tmp_path)
    st, term, detail = tick(_r1(repo, stale, r1_head), head_sha=merged, pr_url=PR, tally=CLEAN,
                            review_base=fresh, config=None, now=NOW, ordinal="r2",
                            numstat_fn=_numstat_in(repo))
    assert term is None and detail["holding"] == []
    assert st["original_diff_lines"] == 100 and st["budget_baseline_head"] == r1_head


def test_merge_from_main_refreshed_base_stale_sha_trips_growth(tmp_path):
    repo, stale, r1_head, _fresh, merged = _merge_from_main_repo(tmp_path)
    st, term, detail = tick(_r1(repo, stale, r1_head), head_sha=merged, pr_url=PR, tally=CLEAN,
                            review_base=stale, config=None, now=NOW, ordinal="r2",
                            numstat_fn=_numstat_in(repo))
    assert term == "budget-exhausted" and st["termination_reason"] == "growth-lines"
    assert detail["measured"] == 600


def test_non_ascii_docs_path_is_excluded_from_budget(tmp_path):
    """core.quotePath quoted `three-pillars-docs/café.md`, so the docs exclusion missed it."""
    import round_budget

    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), "-c", "user.email=t@e", "-c",
                        "user.name=t", *args], check=True, capture_output=True)

    git("init", "-q")
    git("commit", "-q", "--allow-empty", "-m", "base")
    docs = tmp_path / "three-pillars-docs"
    docs.mkdir()
    (docs / "café.md").write_text("x\n" * 50, encoding="utf-8")
    git("add", ".")
    git("commit", "-q", "-m", "docs")
    measure = round_budget.split(git_numstat("HEAD~1", "HEAD", cwd=tmp_path))
    assert measure == {"total": 0, "test_added": 0, "code_added": 0}
