"""test_rerun_phase_tests.py — Tier 3.5 re-run of a phase's Tests at the candidate SHA.

design: local-implement-and-review

Real tmp git repos (`rerun_fixture`), never the ambient repository (M23). Every run
is checked for leftovers: no `.claude/worktrees/tp-rerun-*` dir and no `tp-rerun/*`
branch may survive any path.
"""
from __future__ import annotations

import sys

import pytest

import rerun_phase_tests
import task_scope
from rerun_fixture import DD, PLAN, commit, git, leftovers, make_repo, plan, task

PY = f"{sys.executable} -m pytest"
PASSING = "def test_ok():\n    assert True\n"


def _rerun(repo, sha, base, phase=1, **kw):
    kw.setdefault("test_cmd", PY)
    return rerun_phase_tests.rerun_phase(repo, sha, PLAN, phase, base, design_dir_rel=DD, **kw)


def _clean(repo):
    assert leftovers(repo) == ([], [], 1)


# --- Task 2.1: scratch worktree, plan revision, runner gate ------------------------

def test_plan_absent_skipped(tmp_path):
    repo, base = make_repo(tmp_path)
    sha = commit(repo, {"src/a.py": "x = 1\n"})
    result = _rerun(repo, sha, base)
    assert result["status"] == "skipped"
    assert result["reason"] == "plan-absent"
    assert result["case"] is None and result["nodes"] == []
    _clean(repo)


def test_no_runner_skipped(tmp_path, monkeypatch):
    repo, base = make_repo(tmp_path, pytest_ini=False)
    sha = commit(repo, {PLAN: plan({1: [task("1.1", "`tests/test_a.py::test_ok`")]}),
                        "tests/test_a.py": PASSING})
    monkeypatch.setattr(rerun_phase_tests, "_add_scratch", _never)
    result = _rerun(repo, sha, base, test_cmd=None)
    assert result["status"] == "skipped"
    assert result["reason"] == "no-runner"
    assert result["nodes"] == [] and result["rc"] is None
    _clean(repo)


def _never(*_a, **_k):
    raise AssertionError("a skip path created a scratch worktree")


def test_scratch_removed_on_skip_and_exception(tmp_path, monkeypatch):
    repo, base = make_repo(tmp_path)
    absent = commit(repo, {"src/a.py": "x = 1\n"})
    sha = commit(repo, {PLAN: plan({1: [task("1.1", "`tests/test_a.py::test_ok`")]}),
                        "tests/test_a.py": PASSING})
    with monkeypatch.context() as m:
        m.setattr(rerun_phase_tests, "_add_scratch", _never)
        assert _rerun(repo, absent, base)["reason"] == "plan-absent"
        m.setattr(task_scope, "resolve_runner", lambda root, override: (None, "no-runner"))
        assert _rerun(repo, sha, base)["reason"] == "no-runner"
    _clean(repo)

    seen = []

    def boom(plan_text, phase):
        seen.append(leftovers(repo))
        raise RuntimeError("injected")

    monkeypatch.setattr(task_scope, "phase_tasks", boom)
    with pytest.raises(RuntimeError, match="injected"):
        _rerun(repo, sha, base)
    dirs, branches, count = seen[0]
    assert len(dirs) == 1 and len(branches) == 1 and count == 2  # the scratch existed
    _clean(repo)


# --- Task 2.2: per-task classification (per node, from the junit report) -----------

def _by_task(result):
    return {n["task_id"]: (n["status"], n["reason"]) for n in result["nodes"]}


def test_rc_map_total_real_runs(tmp_path):
    repo, base = make_repo(tmp_path)
    tests = {"tests/test_a.py": PASSING, "tests/test_empty.py": "X = 1\n",
             "tests/test_slow.py": "import time\n\ndef test_slow():\n    time.sleep(30)\n"}
    blocks = [task("2.1", "`tests/test_a.py::test_ok`"), task("2.2", "`tests/test_empty.py`")]
    slow = [task("3.1", "`tests/test_slow.py::test_slow`")]
    sha = commit(repo, {PLAN: plan({1: [], 2: blocks, 3: slow}), **tests})
    result = _rerun(repo, sha, base, phase=2)
    assert _by_task(result) == {"2.1": ("pass", ""),  # a not-Done task's empty file
                                "2.2": ("unverified", "file-no-tests")}
    assert result["status"] == "passed" and result["case"] is None
    timed = _rerun(repo, sha, base, phase=3, timeout=2)
    assert _by_task(timed) == {"3.1": ("unverified", "timeout")}
    for cmd, why in ((f"{PY} --no-such-flag", "no-report"),
                     ("pytest-not-installed", "runner-error")):
        bad = _rerun(repo, sha, base, phase=2, test_cmd=cmd)
        assert set(_by_task(bad).values()) == {("unverified", why)}
        assert bad["case"] is None
    _clean(repo)


def test_non_canonical_targets_unverified_never_case_f(tmp_path):
    """No valid Targets (missing, malformed, `none`) → unverified, even on a Done task
    whose Test prose names a red file: prose is never run."""
    repo, base = make_repo(tmp_path)
    red = "def test_ok():\n    assert False\n"
    sha = commit(repo, {PLAN: plan({1: [
        task("1.1", None, status="Done ✓"),
        task("1.2", "`bash check.sh` exits 0", status="Done ✓"),
        task("1.3", "none", status="Done ✓"),
    ]}), "tests/test_a.py": red})
    result = _rerun(repo, sha, base)
    assert _by_task(result) == {"1.1": ("unverified", "targets-missing"),
                                "1.2": ("unverified", "targets-malformed"),
                                "1.3": ("unverified", "targets-none")}
    assert (result["status"], result["case"]) == ("unverified", None)  # nothing verified
    _clean(repo)


def test_blocked_at_sha_excluded(tmp_path):
    repo, base = make_repo(tmp_path)
    sha = commit(repo, {PLAN: plan({1: [
        task("1.1", "`tests/test_a.py::test_ok`"),
        task("1.2", "`tests/test_a.py::test_never_written`", status="Blocked (x)"),
        task("1.3", "`tests/test_a.py::test_gone`", status="Reversed"),
        task("1.4", "`tests/test_a.py::test_later`", status="Skipped (needs the operator)"),
    ]}), "tests/test_a.py": PASSING})
    result = _rerun(repo, sha, base)
    assert _by_task(result) == {"1.1": ("pass", ""), "1.2": ("excluded", "Blocked"),
                                "1.3": ("excluded", "Reversed"), "1.4": ("excluded", "Skipped")}
    assert result["status"] == "passed"
    _clean(repo)


def test_done_row_still_rerun(tmp_path):
    """impl-audit-1 #1: dispatch skips Done rows; the Tier 3.5 re-run still runs them."""
    repo, base = make_repo(tmp_path)
    sha = commit(repo, {PLAN: plan({1: [
        task("1.1", "`tests/test_a.py::test_ok`", status="Done ✓"),
        task("1.2", "`tests/test_a.py::test_red`", status="Done ✓"),
    ]}), "tests/test_a.py": PASSING + "\n\ndef test_red():\n    assert False\n"})
    result = _rerun(repo, sha, base)
    assert _by_task(result) == {"1.1": ("pass", ""), "1.2": ("failed", "red")}
    assert result["case"] == "f"
    _clean(repo)


def test_skipped_pre_exists_rerun(tmp_path):
    repo, base = make_repo(tmp_path)
    sha = commit(repo, {PLAN: plan({1: [
        task("1.1", "`tests/test_a.py::test_ok`", status="Skipped (pre-exists)"),
        task("1.2", "`tests/test_a.py::test_missing`", status="Skipped (pre-exists)"),
    ]}), "tests/test_a.py": PASSING})
    result = _rerun(repo, sha, base)
    assert _by_task(result)["1.1"] == ("pass", "")
    # The claim is checked, not trusted (impl-audit-1 #19): an absent node is never a
    # pass; it may be deselected by the repo's config, so it is unverified (A30).
    assert _by_task(result)["1.2"] == ("unverified", "node-absent")
    assert result["case"] is None
    _clean(repo)


def test_targets_are_repo_relative_and_verbatim(tmp_path):
    """A target path is read as written, from the repo root: a basename is never
    resolved through the File field."""
    repo, base = make_repo(tmp_path)
    sha = commit(repo, {PLAN: plan({1: [
        task("1.1", "`tests/test_a.py::test_ok`", files="`tests/test_a.py`"),
        task("1.2", "`test_a.py::test_ok`", files="`tests/test_a.py`"),
    ]}), "tests/test_a.py": PASSING})
    result = _rerun(repo, sha, base)
    assert _by_task(result) == {"1.1": ("pass", ""),
                                "1.2": ("unverified", "test-file-absent")}
    spec = {n["task_id"]: n["spec"] for n in result["nodes"]}
    assert spec["1.1"] == "tests/test_a.py::test_ok"
    _clean(repo)


def test_scratch_removed_after_pass_and_fail(tmp_path):
    repo, base = make_repo(tmp_path)
    ok = commit(repo, {PLAN: plan({1: [task("1.1", "`tests/test_a.py::test_ok`")]}),
                       "tests/test_a.py": PASSING})
    assert _rerun(repo, ok, base)["status"] == "passed"
    _clean(repo)
    red = commit(repo, {"tests/test_a.py": "def test_ok():\n    assert False\n"})
    assert _rerun(repo, red, base)["status"] == "failed"
    _clean(repo)


def test_scratch_named_branch_symbolic_ref(tmp_path):
    probe = ("import subprocess\n\n"
             "def test_branch():\n"
             "    out = subprocess.run(['git', 'symbolic-ref', '--short', 'HEAD'],\n"
             "                         capture_output=True, text=True, check=True)\n"
             "    assert out.stdout.startswith('tp-rerun/')\n")
    repo, base = make_repo(tmp_path)
    sha = commit(repo, {PLAN: plan({1: [task("1.1", "`tests/test_m23.py::test_branch`")]}),
                        "tests/test_m23.py": probe})
    result = _rerun(repo, sha, base)
    assert _by_task(result) == {"1.1": ("pass", "")}
    _clean(repo)


def test_test_file_absent_unverified(tmp_path):
    repo, base = make_repo(tmp_path)
    sha = commit(repo, {PLAN: plan({1: [task("1.1", "`tests/test_gone.py::test_ok`")]})})
    result = _rerun(repo, sha, base)
    assert _by_task(result) == {"1.1": ("unverified", "test-file-absent")}
    assert result["case"] is None
    _clean(repo)


# --- Task 2.4: changed-files classification (case g log-only) ----------------------

def test_escape_logged_not_gated(tmp_path):
    repo, base = make_repo(tmp_path)
    sha = commit(repo, {PLAN: plan({1: [task("1.1", "`tests/test_a.py::test_ok`"),
                                        task("1.2", None, files="the helper module")]}),
                        "tests/test_a.py": PASSING, "src/a.py": "A = 1\n",
                        "src/stray.py": "B = 2\n"})
    result = _rerun(repo, sha, base)
    assert result["escaped_files"] == ["src/stray.py"]
    assert result["unparsed_files"] == ["the helper module"]
    assert result["status"] == "passed" and result["case"] is None
    _clean(repo)


def test_design_dir_changes_allowed(tmp_path):
    repo, base = make_repo(tmp_path)
    sha = commit(repo, {PLAN: plan({1: [task("1.1", "`tests/test_a.py::test_ok`")]}),
                        f"{DD}/decisions.md": "# log\n", "tests/test_a.py": PASSING})
    assert _rerun(repo, sha, base)["escaped_files"] == []
    _clean(repo)


def test_base_ref_moved_no_false_escape(tmp_path):
    repo, base = make_repo(tmp_path)
    sha = commit(repo, {PLAN: plan({1: [task("1.1", "`tests/test_a.py::test_ok`")]}),
                        "tests/test_a.py": PASSING, "src/a.py": "A = 1\n"})
    git(repo, "checkout", "-q", "-b", "moved", base)
    moved = commit(repo, {"docs/after-dispatch.md": "landed on the base ref later\n"})
    git(repo, "checkout", "-q", "main")
    result = _rerun(repo, sha, moved)
    assert result["escaped_files"] == []
    assert result["status"] == "passed"
    _clean(repo)


def test_wrapper_shaped_call_absolute_paths(tmp_path):
    """The wrapper passes its cwd and an absolute design dir; both are normalized."""
    repo, base = make_repo(tmp_path)
    sha = commit(repo, {PLAN: plan({1: [task("1.1", "`tests/test_a.py::test_ok`")]}),
                        f"{DD}/decisions.md": "# log\n", "tests/test_a.py": PASSING})
    result = rerun_phase_tests.rerun_phase(repo / "tests", sha, str(repo / PLAN), 1, base,
                                           design_dir_rel=str(repo / DD), test_cmd=PY)
    assert _by_task(result) == {"1.1": ("pass", "")}
    assert result["escaped_files"] == []
    _clean(repo)


def test_files_escape_gates_pinned_off():
    assert rerun_phase_tests.FILES_ESCAPE_GATES is False
