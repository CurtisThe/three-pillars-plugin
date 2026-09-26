"""test_rerun_phase_budget.py — the Tier 3.5 re-run ends inside one Bash call.

design: local-implement-and-review (impl-audit-1 #5, #6)

Every run is clipped to a phase-wide budget; running out → ``skipped`` ``timeout``
(the wrapper self-logs ``rerun-skipped timeout``, exit 0), never a killed wrapper
that returns no envelope and leaks its scratch. Real tmp repos only.
"""
from __future__ import annotations

import sys

import rerun_phase_tests
from rerun_fixture import DD, PLAN, commit, leftovers, make_repo, plan, task

PY = f"{sys.executable} -m pytest"
SLOW = "import time\n\n\ndef test_slow():\n    time.sleep(30)\n"


def _rerun(repo, sha, base, **kw):
    return rerun_phase_tests.rerun_phase(repo, sha, PLAN, 1, base, design_dir_rel=DD,
                                         test_cmd=PY, **kw)


def test_budget_exhausted_is_skipped_timeout(tmp_path):
    repo, base = make_repo(tmp_path)
    sha = commit(repo, {PLAN: plan({1: [task("1.1", "`tests/test_s.py::test_slow`"),
                                        task("1.2", "`tests/test_s.py::test_slow`")]}),
                        "tests/test_s.py": SLOW})
    result = _rerun(repo, sha, base, budget=3)
    assert (result["status"], result["reason"], result["case"]) == ("skipped", "timeout", None)
    assert leftovers(repo) == ([], [], 1)


def test_default_budget_fits_the_bash_ceiling():
    assert 0 < rerun_phase_tests.PHASE_BUDGET_S <= 540  # Bash max is 600 s


RED = "def test_ok():\n    assert False\n"


def test_unresolved_base_is_distinct_skip(tmp_path, monkeypatch):
    """impl-audit-1 #6: a wrong phase_base_sha is `base-unresolved`, not `env-broken`."""
    repo, _base = make_repo(tmp_path)
    sha = commit(repo, {PLAN: plan({1: [task("1.1", "`tests/test_a.py::test_ok`")]}),
                        "tests/test_a.py": RED})
    monkeypatch.setattr(rerun_phase_tests, "_add_scratch", _never)
    result = _rerun(repo, sha, "f" * 40)
    assert (result["status"], result["reason"], result["case"]) == (
        "skipped", "base-unresolved", None)
    assert leftovers(repo) == ([], [], 1)


def _never(*_a, **_k):
    raise AssertionError("an unresolved base must not create a scratch worktree")


def test_short_base_resolves_to_full_sha(tmp_path):
    repo, base = make_repo(tmp_path)
    sha = commit(repo, {PLAN: plan({1: [task("1.1", "`tests/test_a.py::test_ok`")]}),
                        "tests/test_a.py": RED})
    result = _rerun(repo, sha, base[:10])
    assert (result["status"], result["case"]) == ("failed", "f")
