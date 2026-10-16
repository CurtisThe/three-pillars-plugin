"""test_rerun_phase_junit.py — the Tier 3.5 re-run judges declared nodes by the report.

design: local-implement-and-review (PR #165 rulings, amendments A29, A30)

Each declared target's verdict is read per node from the run's ``--junitxml`` report,
never from the exit code or from which config turns xdist on: (a) an absent declared
node under xdist is unverified, never case f (A30: the config may deselect it), (b) a
red one is case f after the control, (c) a green one passes, (d) a candidate
``conftest.py`` that breaks the run or lies about the exit status never passes, (e) no
report or a garbage one is unverified. Real tmp repos via `rerun_fixture` (M23).
"""
from __future__ import annotations

import shlex
import sys

import pytest

import rerun_phase_tests
from rerun_fixture import DD, PLAN, commit, leftovers, make_repo, plan, task

PY = f"{shlex.quote(sys.executable)} -m pytest"
PASSING = "def test_ok():\n    assert True\n"
RED = "def test_red():\n    assert False, 'MARKER-RED'\n"
XDIST_INI = {"pytest.ini": "[pytest]\naddopts = -n 2\n"}
# A wrapper runner (a script, `tox -e`, `make`-like): no token is `pytest`. It is a script
# file, since an override outside the argv-safe language is refused (PR #170 r4).
WRAPPED = f'exec {PY} "$@"\n'
LIAR = "def pytest_sessionfinish(session, exitstatus):\n    session.exitstatus = 0\n"


def _wrap(tmp_path, body):
    (tmp_path / "wrap.sh").write_text(body, encoding="utf-8")
    return f"sh {tmp_path / 'wrap.sh'}"


def _rerun(repo, sha, base, test_cmd=PY):
    return rerun_phase_tests.rerun_phase(repo, sha, PLAN, 1, base, design_dir_rel=DD,
                                         test_cmd=test_cmd)


def _nodes(result):
    return {n["task_id"]: (n["status"], n["reason"]) for n in result["nodes"]}


def _xdist_repo(tmp_path, files):
    pytest.importorskip("xdist")
    repo, _ = make_repo(tmp_path, pytest_ini=False)
    base = commit(repo, {**XDIST_INI, "tests/test_a.py": PASSING}, "xdist config")
    return repo, base, commit(repo, files)


@pytest.mark.parametrize("wrapper", [None, WRAPPED], ids=["pytest", "wrapper"])
def test_a_absent_node_under_xdist_is_unverified(tmp_path, wrapper):
    runner = _wrap(tmp_path, wrapper) if wrapper else PY
    repo, base, sha = _xdist_repo(tmp_path, {PLAN: plan({1: [
        task("1.1", "`tests/test_a.py::test_ok`", status="Done"),
        task("1.2", "`tests/test_a.py::test_never_written`", status="Done")]})})
    result = _rerun(repo, sha, base, runner)
    assert _nodes(result) == {"1.1": ("pass", ""), "1.2": ("unverified", "node-absent")}
    assert (result["status"], result["case"]) == ("passed", None)
    assert leftovers(repo) == ([], [], 1)


def test_b_red_node_under_xdist_is_case_f_after_control(tmp_path):
    repo, base, sha = _xdist_repo(tmp_path, {
        PLAN: plan({1: [task("1.1", "`tests/test_b.py::test_red`", status="Done")]}),
        "tests/test_b.py": RED})
    result = _rerun(repo, sha, base)
    assert _nodes(result) == {"1.1": ("failed", "red")}
    assert (result["status"], result["case"]) == ("failed", "f")
    assert result["control"]["rc"] in (0, 5) and "MARKER-RED" in result["output_tail"]


def test_c_green_node_under_xdist_passes(tmp_path):
    repo, base, sha = _xdist_repo(tmp_path, {PLAN: plan({1: [
        task("1.1", "`tests/test_a.py::test_ok`", status="Done"),
        task("1.2", "`tests/test_a.py`", status="Done")]})})
    result = _rerun(repo, sha, base)
    assert _nodes(result) == {"1.1": ("pass", ""), "1.2": ("pass", "")}
    assert (result["status"], result["case"]) == ("passed", None)


def test_d_candidate_conftest_never_passes(tmp_path):
    repo, base = make_repo(tmp_path)
    broken = commit(repo, {
        PLAN: plan({1: [task("1.1", "`tests/test_a.py::test_ok`", status="Done")]}),
        "tests/test_a.py": PASSING, "tests/conftest.py": "import no_such_mod_q\n"})
    result = _rerun(repo, broken, base)
    assert result["status"] in ("unverified", "failed"), result
    assert _nodes(result)["1.1"][0] != "pass"
    lying = commit(repo, {  # the exit code says 0; the report says red
        PLAN: plan({1: [task("1.1", "`tests/test_b.py::test_red`", status="Done")]}),
        "tests/conftest.py": LIAR, "tests/test_b.py": RED})
    result = _rerun(repo, lying, base)
    assert _nodes(result) == {"1.1": ("failed", "red")}
    assert (result["status"], result["case"]) == ("failed", "f")


_DROP = f'exec {PY} "$1"\n'  # runs the target, drops the flags
_GARBAGE = (f'{PY} "$@"; rc=$?; for a; do case "$a" in --junitxml=*) '
            'echo "<testsuites><testcase" > "${a#--junitxml=}";; esac; done; exit $rc\n')


@pytest.mark.parametrize("wrapper", [_DROP, _GARBAGE], ids=["no-report", "garbage"])
def test_e_no_or_garbage_report_is_unverified(tmp_path, wrapper):
    runner = _wrap(tmp_path, wrapper)
    repo, base = make_repo(tmp_path)
    sha = commit(repo, {PLAN: plan({1: [task("1.1", "`tests/test_a.py::test_ok`",
                                              status="Done")]}),
                        "tests/test_a.py": PASSING})
    result = _rerun(repo, sha, base, runner)
    assert _nodes(result) == {"1.1": ("unverified", "no-report")}
    assert (result["status"], result["reason"], result["case"]) == (
        "unverified", "nothing-verified", None)
    assert leftovers(repo) == ([], [], 1)
