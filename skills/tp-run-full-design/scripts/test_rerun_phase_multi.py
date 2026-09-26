"""test_rerun_phase_multi.py — the Tier 3.5 re-run of a task declaring several targets.

design: local-implement-and-review (PR #165; operator rulings on #165, C3)

Every stage uses the task's full declared target list: the run, the confirm, the
environment control (`_control`) and the case-g escape check (`_classify_changes`). The
order of the **Targets** items never matters, a whole-file item runs the whole file, and
case f fires only from a declared target. Real tmp git repos (`rerun_fixture`), never the
ambient repository (M23).
"""
from __future__ import annotations

import sys

import pytest

import rerun_phase_tests
from rerun_fixture import DD, PLAN, commit, leftovers, make_repo, plan, task

PY = f"{sys.executable} -m pytest -q -p no:cacheprovider"
PASSING = "def test_ok():\n    assert True\n"
RED = "def test_ok():\n    assert False\n"
TWO = "def test_ok():\n    assert True\n\n\ndef test_red():\n    assert False\n"


def _rerun(repo, sha, base):
    result = rerun_phase_tests.rerun_phase(repo, sha, PLAN, 1, base, design_dir_rel=DD,
                                           test_cmd=PY)
    assert leftovers(repo) == ([], [], 1)
    return result


def _by_task(result):
    return {n["task_id"]: (n["status"], n["reason"]) for n in result["nodes"]}


_FORMS = [
    "`tests/test_a.py`, `tests/test_b.py`",
    "`tests/test_b.py`, `tests/test_a.py`",
    "`tests/test_a.py::test_ok`, `tests/test_b.py::test_ok`",
    "`tests/test_b.py::test_ok`, `tests/test_a.py::test_ok`",
]


@pytest.mark.parametrize("targets", _FORMS, ids=["files", "files-reordered", "nodes",
                                                 "nodes-reordered"])
def test_red_second_file_fails_the_phase_in_any_order(tmp_path, targets):
    repo, base = make_repo(tmp_path)
    sha = commit(repo, {PLAN: plan({1: [task("1.1", targets)]}),
                        "tests/test_a.py": PASSING, "tests/test_b.py": RED})
    result = _rerun(repo, sha, base)
    assert (result["status"], result["case"]) == ("failed", "f")
    assert _by_task(result) == {"1.1": ("failed", "red")}
    files = {t.partition("::")[0] for t in result["nodes"][0]["targets"]}
    assert files == {"tests/test_a.py", "tests/test_b.py"}


@pytest.mark.parametrize("targets", [
    "`tests/test_a.py`, `tests/test_a.py::test_ok`",
    "`tests/test_a.py::test_ok`, `tests/test_a.py`",
], ids=["file-first", "node-first"])
def test_whole_file_item_runs_the_whole_file_in_any_order(tmp_path, targets):
    """A bare file anywhere in the field runs the whole file, so a red sibling node
    of the declared node is caught (the r3 fail-open narrowing cannot recur)."""
    repo, base = make_repo(tmp_path)
    sha = commit(repo, {PLAN: plan({1: [task("1.1", targets)]}), "tests/test_a.py": TWO})
    result = _rerun(repo, sha, base)
    assert _by_task(result) == {"1.1": ("failed", "red")}
    assert result["nodes"][0]["targets"] == ["tests/test_a.py"]


def test_undeclared_red_is_not_case_f(tmp_path):
    """Case f fires only from a declared target: a red test nobody declared is not run."""
    repo, base = make_repo(tmp_path)
    sha = commit(repo, {PLAN: plan({1: [task("1.1", "`tests/test_a.py::test_ok`")]}),
                        "tests/test_a.py": TWO, "tests/test_b.py": RED})
    result = _rerun(repo, sha, base)
    assert (result["status"], result["case"]) == ("passed", None)
    assert _by_task(result) == {"1.1": ("pass", "")}


def test_env_fault_in_second_file_is_env_broken_not_case_f(tmp_path):
    """The control collects every declared file, so a collection-level environment
    fault in the second file (broken at base too) never escalates as case f."""
    repo, _ = make_repo(tmp_path)
    importer = "import envfault  # noqa: F401\n\n" + PASSING
    base = commit(repo, {"tests/envfault.py": "raise ImportError('broken env')\n",
                         "tests/test_a.py": PASSING, "tests/test_b.py": importer})
    sha = commit(repo, {PLAN: plan({1: [task("1.1", _FORMS[0])]}),
                        "tests/test_a.py": PASSING + "\n\ndef test_new():\n    pass\n"})
    result = _rerun(repo, sha, base)
    assert (result["status"], result["reason"], result["case"]) == (
        "skipped", "env-broken", None)
    assert sorted(result["control"]["targets"]) == ["tests/test_a.py", "tests/test_b.py"]


def test_second_declared_file_is_not_an_escape(tmp_path):
    repo, base = make_repo(tmp_path)
    sha = commit(repo, {PLAN: plan({1: [task("1.1", _FORMS[2])]}), "src/a.py": "A = 1\n",
                        "tests/test_a.py": PASSING, "tests/test_b.py": PASSING})
    result = _rerun(repo, sha, base)
    assert result["status"] == "passed"
    assert result["escaped_files"] == []


@pytest.mark.parametrize("marker", ["", " (new)"], ids=["existing", "new"])
def test_declared_file_absent_on_done_task_is_case_f(tmp_path, marker):
    """A declared file (created by the task or not) missing at the SHA on a Done task is
    an f-candidate, still subject to the environment control."""
    repo, base = make_repo(tmp_path)
    targets = f"`tests/test_a.py::test_ok`, `tests/test_gone.py::test_ok`{marker}"
    sha = commit(repo, {PLAN: plan({1: [task("1.1", targets, status="Done ✓")]}),
                        "tests/test_a.py": PASSING})
    result = _rerun(repo, sha, base)
    assert (result["status"], result["case"]) == ("failed", "f")
    assert _by_task(result) == {"1.1": ("failed", "test-file-absent")}
    assert result["control"]["rc"] in (0, 5)


def test_absent_declared_file_on_open_task_leaves_a_green_run_unverified(tmp_path):
    repo, base = make_repo(tmp_path)
    targets = "`tests/test_a.py::test_ok`, `tests/test_later.py::test_ok` (new)"
    sha = commit(repo, {PLAN: plan({1: [task("1.1", targets)]}), "tests/test_a.py": PASSING})
    result = _rerun(repo, sha, base)
    assert _by_task(result) == {"1.1": ("unverified", "test-file-absent")}
    assert result["nodes"][0]["targets"] == ["tests/test_a.py::test_ok"]
