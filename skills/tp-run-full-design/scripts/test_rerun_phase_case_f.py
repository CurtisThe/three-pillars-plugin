"""test_rerun_phase_case_f.py — when a re-run failure becomes case f (and when not).

design: local-implement-and-review (design-audit-3 #6)

An f-candidate (a declared node red or uncollectable in the run's junit report, A29,
or a ``Done`` task's declared file absent; an absent node is unverified, A30) escalates
as case f only after two checks in the same scratch: a *confirm* re-run of the failing
nodes (a pass → ``unverified (flaky)``) and one per-phase *environment control* at
``phase_base_sha`` (``--collect-only``; a failing control → ``rerun-skipped
(env-broken)``). Real tmp repos via `rerun_fixture` (M23).
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


def _node(result, tid):
    return next(n for n in result["nodes"] if n["task_id"] == tid)


def _phase(*blocks):
    return plan({1: list(blocks)})


def test_red_node_confirmed_is_case_f_with_output_tail(tmp_path):
    repo, base = make_repo(tmp_path)
    red = "def test_red():\n    assert False, 'MARKER-RED-4217'\n"
    sha = commit(repo, {PLAN: _phase(task("1.1", "`tests/test_a.py::test_red`"),
                                     task("1.2", "`tests/test_b.py::test_ok`")),
                        "tests/test_a.py": red, "tests/test_b.py": PASSING})
    result = _rerun(repo, sha, base)
    assert result["status"] == "failed" and result["case"] == "f"
    assert (_node(result, "1.1")["status"], _node(result, "1.1")["reason"]) == ("failed", "red")
    assert _node(result, "1.2")["status"] == "pass"
    assert "MARKER-RED-4217" in _node(result, "1.1")["output_tail"]
    assert "MARKER-RED-4217" in result["output_tail"]
    assert result["control"]["rc"] in (0, 5)
    assert leftovers(repo) == ([], [], 1)


def test_absent_node_is_unverified_not_case_f(tmp_path):
    """A node absent from a cleanly collected file may be deselected by the repo's
    config: unverified, never case f (A30; it was case f before)."""
    repo, base = make_repo(tmp_path)
    sha = commit(repo, {PLAN: _phase(task("1.1", "`tests/test_a.py::test_never_written`",
                                          status="Done")),
                        "tests/test_a.py": PASSING})
    result = _rerun(repo, sha, base)
    assert (result["status"], result["case"]) == ("unverified", None)
    assert (_node(result, "1.1")["status"], _node(result, "1.1")["reason"]) == (
        "unverified", "node-absent")


def test_collection_error_is_case_f(tmp_path):
    repo, _ = make_repo(tmp_path)
    base = commit(repo, {"tests/test_a.py": PASSING})  # collects cleanly at the base
    sha = commit(repo, {PLAN: _phase(task("1.1", "`tests/test_a.py::test_ok`")),
                        "tests/test_a.py": "def test_ok(:\n    pass\n"})
    result = _rerun(repo, sha, base)
    assert result["case"] == "f" and result["status"] == "failed"
    assert _node(result, "1.1")["reason"] == "collection-error"
    assert result["control"]["rc"] == 0


def test_flaky_node_unverified(tmp_path):
    repo, base = make_repo(tmp_path)
    flaky = ("from pathlib import Path\n\n"
             "def test_flaky():\n"
             "    marker = Path(__file__).with_name('.flaky-seen')\n"
             "    if not marker.exists():\n"
             "        marker.write_text('1')\n"
             "        assert False, 'first run fails'\n")
    sha = commit(repo, {PLAN: _phase(task("1.1", "`tests/test_a.py::test_flaky`")),
                        "tests/test_a.py": flaky})
    result = _rerun(repo, sha, base)
    assert (_node(result, "1.1")["status"], _node(result, "1.1")["reason"]) == (
        "unverified", "flaky")
    # a flaky node alone verified nothing: the phase is unverified, never passed
    assert (result["status"], result["reason"], result["case"]) == (
        "unverified", "nothing-verified", None)
    assert result["control"] is None  # no confirmed candidate, no control run


def test_env_broken_control_skips(tmp_path):
    repo, _ = make_repo(tmp_path)
    importer = "import envfault  # noqa: F401\n\n" + PASSING
    base = commit(repo, {"tests/envfault.py": "raise ImportError('broken env')\n",
                         "tests/test_a.py": importer})
    sha = commit(repo, {PLAN: _phase(task("1.1", "`tests/test_a.py::test_ok`")),
                        "tests/test_a.py": importer + "\n\ndef test_new():\n    pass\n"})
    result = _rerun(repo, sha, base)
    assert result["case"] is None
    assert result["status"] == "skipped" and result["reason"] == "env-broken"
    assert (_node(result, "1.1")["status"], _node(result, "1.1")["reason"]) == (
        "rerun-skipped", "env-broken")
    assert result["control"]["rc"] not in (0, 5)
    assert leftovers(repo) == ([], [], 1)


def test_done_task_test_file_absent_is_case_f(tmp_path):
    """impl-audit-1 #11: a Done task whose Test file never landed is "missing at that
    SHA" (Behavior 10), not merely unverified; a not-Done task stays unverified."""
    repo, base = make_repo(tmp_path)
    sha = commit(repo, {PLAN: _phase(
        task("1.1", "`tests/test_gone.py::test_ok`", status="Done ✓"),
        task("1.2", "`tests/test_later.py::test_ok`"))})
    result = _rerun(repo, sha, base)
    assert (result["status"], result["case"]) == ("failed", "f")
    assert (_node(result, "1.1")["status"], _node(result, "1.1")["reason"]) == (
        "failed", "test-file-absent")
    assert (_node(result, "1.2")["status"], _node(result, "1.2")["reason"]) == (
        "unverified", "test-file-absent")
    assert result["control"]["rc"] in (0, 5)
    assert "tests/test_gone.py: not in the tree at the SHA" in result["output_tail"]
    assert leftovers(repo) == ([], [], 1)


# One config-file form and one runner form. The verdict is per node from the junit
# report, so whichever config turns xdist on is irrelevant (PR #165 ruling, A29).
_XDIST_FORMS = {
    "pyproject-tool-pytest": ({"pyproject.toml": '[tool.pytest]\naddopts = ["-n", "2"]\n'}, PY),
    "test-cmd-n2": ({"pytest.ini": "[pytest]\n"}, f"{PY} -n 2"),
}


@pytest.mark.parametrize("form", sorted(_XDIST_FORMS))
def test_xdist_absent_node_is_unverified_and_never_masks_red(tmp_path, form):
    """Under xdist an absent node exits 5 and has no testcase: unverified (A30
    supersedes round 6's case f), and beside a red node the red still wins: case f."""
    pytest.importorskip("xdist")
    config, test_cmd = _XDIST_FORMS[form]
    repo, _ = make_repo(tmp_path, pytest_ini=False)
    base = commit(repo, config, "xdist config")
    sha = commit(repo, {PLAN: _phase(
        task("1.1", "`tests/test_a.py::test_gone`", status="Done"),
        task("1.2", "`tests/test_a.py::test_red`, `tests/test_a.py::test_gone`",
             status="Done")),
        "tests/test_a.py": "def test_red():\n    assert False\n"})
    result = rerun_phase_tests.rerun_phase(repo, sha, PLAN, 1, base, design_dir_rel=DD,
                                           test_cmd=test_cmd)
    assert (result["status"], result["case"]) == ("failed", "f"), result["nodes"]
    assert (_node(result, "1.1")["status"], _node(result, "1.1")["reason"]) == (
        "unverified", "node-absent")
    assert (_node(result, "1.2")["status"], _node(result, "1.2")["reason"]) == (
        "failed", "red")
    assert leftovers(repo) == ([], [], 1)
