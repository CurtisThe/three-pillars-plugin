"""test_rerun_phase_unverified.py — a phase that verified nothing is never ``passed``.

design: local-implement-and-review (PR #165 r7, r9, amendments A28, A29, A30)

When no declared target passed and no f-candidate was confirmed — no report shows a
declared target passing, or a candidate ``conftest.py`` broke collection for all of them
— the re-run reports ``unverified (nothing-verified)``: not a pass, and not case f by
itself. A declared node absent from the report, or a declared file with no testcase,
is unverified (the config may deselect it, A30) and never masks a red target beside
it; a ``Done`` task's declared file missing from the tree stays case f.
Real tmp repos via `rerun_fixture` (M23).
"""
from __future__ import annotations

import sys

import pytest

import rerun_phase_tests
from rerun_fixture import DD, PLAN, commit, leftovers, make_repo, plan, task

PY = f"{sys.executable} -m pytest"
PASSING = "def test_ok():\n    assert True\n"


def _rerun(repo, sha, base):
    return rerun_phase_tests.rerun_phase(repo, sha, PLAN, 1, base, design_dir_rel=DD,
                                         test_cmd=PY)


def test_conftest_import_error_is_unverified_not_passed(tmp_path):
    repo, _ = make_repo(tmp_path)
    base = commit(repo, {"tests/test_a.py": PASSING})
    sha = commit(repo, {PLAN: plan({1: [task("1.1", "`tests/test_a.py::test_ok`",
                                              status="Done")]}),
                        "tests/conftest.py": "import no_such_module_xyz  # noqa: F401\n"})
    result = _rerun(repo, sha, base)
    assert (result["status"], result["reason"], result["case"]) == (
        "unverified", "nothing-verified", None), result["nodes"]
    assert result["nodes"][0]["status"] == "unverified"
    assert leftovers(repo) == ([], [], 1)


def test_every_target_without_tests_is_unverified(tmp_path):
    """Declared files with no testcase in the report: unverified (A29, A30), so the
    phase verified nothing."""
    repo, base = make_repo(tmp_path)
    empty = "HELPER = 1\n"  # a test file that collects no tests
    sha = commit(repo, {PLAN: plan({1: [
        task("1.1", "`tests/test_a.py`"), task("1.2", "`tests/test_b.py`")]}),
        "tests/test_a.py": empty, "tests/test_b.py": empty})
    result = _rerun(repo, sha, base)
    assert [(n["status"], n["reason"]) for n in result["nodes"]] == [
        ("unverified", "file-no-tests")] * 2
    assert (result["status"], result["reason"], result["case"]) == (
        "unverified", "nothing-verified", None)
    assert leftovers(repo) == ([], [], 1)


def test_done_file_without_tests_is_unverified(tmp_path):
    """A ``Done`` task's present file with no testcase may be deselected by the repo's
    config: unverified, never case f (A30 supersedes A29's case f here)."""
    repo, base = make_repo(tmp_path)
    sha = commit(repo, {PLAN: plan({1: [task("1.1", "`tests/test_a.py`", status="Done")]}),
                        "tests/test_a.py": "HELPER = 1\n"})
    result = _rerun(repo, sha, base)
    assert (result["status"], result["case"]) == ("unverified", None), result["nodes"]
    assert (result["nodes"][0]["status"], result["nodes"][0]["reason"]) == (
        "unverified", "file-no-tests")
    assert leftovers(repo) == ([], [], 1)


def test_one_passing_target_still_passes(tmp_path):
    """The rule is "nothing verified": one green target keeps the phase ``passed``."""
    repo, base = make_repo(tmp_path)
    sha = commit(repo, {PLAN: plan({1: [
        task("1.1", "`tests/test_a.py::test_ok`", status="Done"),
        task("1.2", "`tests/test_b.py`")]}),
        "tests/test_a.py": PASSING, "tests/test_b.py": "HELPER = 1\n"})
    result = _rerun(repo, sha, base)
    assert (result["status"], result["case"]) == ("passed", None)


RED = "def test_red():\n    assert False\n"


@pytest.mark.parametrize("targets, want", [
    ("`tests/test_0.py`, `tests/test_r.py::test_red`", "red"),
    ("`tests/test_r.py::test_red`, `tests/test_0.py`", "red"),
    ("`tests/test_a.py::test_never_written`, `tests/test_r.py::test_red`", "red"),
    ("`tests/test_a.py::test_never_written`, `tests/test_bad.py`", "collection-error"),
    ("`tests/test_0.py`, `tests/test_gone.py`", "test-file-absent"),
], ids=["no-tests-then-red", "red-then-no-tests", "absent-node-then-red",
        "absent-node-then-collection-error", "no-tests-then-missing-file"])
def test_unverified_target_never_masks_red_or_missing_file(tmp_path, targets, want):
    """Each declared target is judged on its own (c17d227c): an unverified target
    (``file-no-tests``, ``node-absent``) never hides a red, collection-error or missing
    declared file beside it in the same ``Done`` task: case f."""
    repo, base = make_repo(tmp_path)
    sha = commit(repo, {PLAN: plan({1: [
        task("1.1", "`tests/test_a.py::test_ok`", status="Done"),
        task("1.2", targets, status="Done")]}),
        "tests/test_a.py": PASSING, "tests/test_0.py": "HELPER = 1\n",
        "tests/test_r.py": RED, "tests/test_bad.py": "def test_q(:\n    pass\n"})
    result = _rerun(repo, sha, base)
    assert (result["status"], result["case"]) == ("failed", "f"), result["nodes"]
    assert [(n["status"], n["reason"]) for n in result["nodes"]] == [
        ("pass", ""), ("failed", want)]
    assert leftovers(repo) == ([], [], 1)
