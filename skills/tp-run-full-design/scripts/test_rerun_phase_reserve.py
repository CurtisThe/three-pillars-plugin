"""test_rerun_phase_reserve.py — a slow phase never drops the reds it already saw.

design: local-implement-and-review (impl-audit-2 #1)

Task runs stop at the budget minus a reserve; the reserve confirms and controls the
f-candidates already seen. A red the budget still cuts short is named in the skip
reason and in the wrapper's self-logged line. The Bash call outlasts the ls-remote plus
the budget (code constants). Real tmp repos where a run is involved.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import rerun_budget
import rerun_phase_tests
import run_tier_3_5
import tier_3_5_rerun
from rerun_fixture import DD, PLAN, commit, leftovers, make_repo, plan, task

PY = f"{sys.executable} -m pytest"
FILES = {"tests/test_r.py": "def test_red():\n    assert False\n",
         "tests/test_s.py": "import time\n\n\ndef test_slow():\n    time.sleep(30)\n"}
TASKS = [task("1.1", "`tests/test_r.py::test_red`"), task("1.2", "`tests/test_s.py::test_slow`")]


def _rerun(repo, sha, base, **kw):
    return rerun_phase_tests.rerun_phase(repo, sha, PLAN, 1, base, design_dir_rel=DD,
                                         test_cmd=PY, **kw)


def test_reserve_confirms_a_red_seen_before_the_cut(tmp_path):
    repo, base = make_repo(tmp_path)
    sha = commit(repo, {PLAN: plan({1: TASKS}), **FILES})
    result = _rerun(repo, sha, base, budget=8, reserve=4)
    assert (result["status"], result["case"]) == ("failed", "f")
    assert [(n["task_id"], n["status"]) for n in result["nodes"]] == [("1.1", "failed")]
    assert result["control"]["rc"] in (0, 5)
    assert leftovers(repo) == ([], [], 1)


def test_out_of_budget_names_the_unconfirmed_red(tmp_path, monkeypatch):
    repo, base = make_repo(tmp_path)
    sha = commit(repo, {PLAN: plan({1: TASKS[:1]}), **FILES})

    def _no_time(*_a, **_k):
        raise rerun_phase_tests._OutOfBudget()

    monkeypatch.setattr(rerun_phase_tests, "_control", _no_time)
    result = _rerun(repo, sha, base)
    assert (result["status"], result["reason"], result["case"]) == (
        "skipped", "timeout (unconfirmed red: 1.1)", None)
    assert result["nodes"][0]["status"] == "rerun-skipped"
    lines = tier_3_5_rerun.log_lines(result)
    assert f"{tier_3_5_rerun.LOG_PREFIX} rerun-skipped timeout (unconfirmed red: 1.1)" in lines
    assert any("1.1:unconfirmed-red" in line for line in lines)
    assert leftovers(repo) == ([], [], 1)


def test_default_reserve_is_a_bounded_share():
    assert rerun_budget.reserve_for(480) == rerun_budget.CONFIRM_RESERVE_S == 120
    assert rerun_budget.reserve_for(4) == 1 and rerun_budget.reserve_for(8, 3) == 3


def test_fetch_is_bounded_and_never_raises(monkeypatch):
    seen = {}

    def _slow_git(*_args, timeout=None, **_k):
        seen["timeout"] = timeout
        raise subprocess.TimeoutExpired("git fetch", timeout)

    monkeypatch.setattr(rerun_phase_tests, "_git", _slow_git)
    rerun_phase_tests._fetch(Path("."), "abc", rerun_budget.Deadline(900, 480))
    assert 0 < seen["timeout"] <= rerun_budget.FETCH_TIMEOUT_S


def test_bash_call_outlasts_the_ls_remote_and_the_budget():
    """The wrapper's Bash call (``BASH_TIMEOUT_MS``, at most the tool's 600000 ms) outlasts
    the ls-remote plus the phase budget with a margin."""
    budget = rerun_budget
    assert run_tier_3_5.LS_REMOTE_TIMEOUT_S == budget.LS_REMOTE_TIMEOUT_S
    assert rerun_phase_tests.PHASE_BUDGET_S == budget.PHASE_BUDGET_S
    need_s = budget.PHASE_BUDGET_S + budget.LS_REMOTE_TIMEOUT_S + budget.BASH_MARGIN_S
    assert need_s * 1000 <= budget.BASH_TIMEOUT_MS <= 600000
