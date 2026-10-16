"""test_task_verify_junit.py — ``check`` step 6 judges each declared target by its report.

design: local-implement-and-review (PR #165 ruling, amendment A29)

The exit code never passes a declared target: a conftest that rewrites the status, a
runner that drops the ``--junitxml`` flags, a garbage report, a broken candidate
``conftest.py``, an absent node under any config or a missing file are never PASS. Each
attempt commits the red (its Targets) then the green (``commit_pair``). Real tmp repos
only (``attempt_fixture``, M23).
"""
from __future__ import annotations

import shlex
import sys
from pathlib import Path

import pytest

import task_attempts
import task_verify
from attempt_fixture import DD, commit, commit_pair, make_seat, task_row

PY = shlex.quote(sys.executable)
RUNNER = f"{PY} -m pytest -q"
RED = "def test_a():\n    assert 1 == 2\n"
GREEN = "def test_a():\n    assert 1 == 1\n"
NODE_ROW = {"files": ["skills/a.py"], "targets": "`skills/test_a.py::test_a`"}
# A repo conftest that reports every session as passed: the exit code lies.
LIAR = "def pytest_sessionfinish(session, exitstatus):\n    session.exitstatus = 0\n"


def _attempt(tmp_path: Path, base: dict | None, red: dict, green: dict | None = None):
    """``red`` (the Targets files), then the green: ``skills/a.py`` plus ``green``. With
    no red, the green alone (an implementation-only commit)."""
    _seat, wt = make_seat(tmp_path)
    if base:
        commit(wt, base, "repo config")
    att = task_attempts.open_attempt(wt, "1.1", DD)
    impl = {"skills/a.py": "A = 2\n", **(green or {})}
    if red:
        commit_pair(Path(att["attempt_dir"]), red, impl)
    else:
        commit(Path(att["attempt_dir"]), impl)
    return att


def _check(att, row=None, runner=RUNNER):
    return task_verify.check(att, task_row(**(row or NODE_ROW)), runner, rung="local",
                             timeout=120)


def test_red_under_lying_exit_code_fails(tmp_path):
    att = _attempt(tmp_path, {"conftest.py": LIAR}, {"skills/test_a.py": RED})
    res = _check(att)
    assert (res["verdict"], res["reason"]) == ("FAIL", "red test"), res["test_output_tail"]


def test_red_check_reports_failing_tests_and_targets(tmp_path):
    """A failing check's JSON carries the failed node ids and the red target(s)
    (`junit_verdict.run_judged`'s ``failed_out``)."""
    att = _attempt(tmp_path, None, {"skills/test_a.py": RED})
    res = _check(att)
    assert res["verdict"] == "FAIL"
    assert res["failing_tests"] == ["skills/test_a.py::test_a"]
    assert res["failing_targets"] == ["skills/test_a.py::test_a"]


def test_no_report_is_never_pass(tmp_path):
    """A runner that drops the report flags exits 0 on a green node: no report → FAIL."""
    drop = f"sh -c {shlex.quote(f'exec {PY} -m pytest -q \"$1\"')} sh"
    att = _attempt(tmp_path, None, {"skills/test_a.py": GREEN})
    res = _check(att, runner=drop)
    assert (res["verdict"], res["reason"]) == ("FAIL", "unverified test (no-report)")


def test_garbage_report_is_never_pass(tmp_path):
    script = (f'{PY} -m pytest -q "$@"; rc=$?; for a; do case "$a" in --junitxml=*) '
              'echo "not <xml" > "${a#--junitxml=}";; esac; done; exit $rc')
    att = _attempt(tmp_path, None, {"skills/test_a.py": GREEN})
    res = _check(att, runner=f"sh -c {shlex.quote(script)} sh")
    assert (res["verdict"], res["reason"]) == ("FAIL", "unverified test (no-report)")


def test_candidate_conftest_import_error_is_never_pass(tmp_path):
    conftest = {"skills/conftest.py": "import no_such_mod_x\n"}  # a File: in the green
    row = {"files": ["skills/a.py", "skills/conftest.py"],
           "targets": "`skills/test_a.py::test_a`"}
    res = _check(_attempt(tmp_path, None, {"skills/test_a.py": GREEN}, conftest), row)
    assert res["verdict"] == "FAIL" and res["reason"].startswith("unverified test"), res


@pytest.mark.parametrize("config", ["-n 2", "-p no:xdist"])
def test_missing_node_under_any_config_fails(tmp_path, config):
    if "no:" not in config:
        pytest.importorskip("xdist")
    base = {"pytest.ini": f"[pytest]\naddopts = {config}\n"}
    row = {"files": ["skills/a.py"], "targets": "`skills/test_a.py::test_gone`"}
    res = _check(_attempt(tmp_path, base, {"skills/test_a.py": GREEN}), row)
    assert (res["verdict"], res["reason"]) == ("FAIL", "unverified test (node-absent)"), res
    (tmp_path / "g").mkdir()
    green = _check(_attempt(tmp_path / "g", base, {"skills/test_a.py": GREEN}))
    assert green["verdict"] == "PASS", green["test_output_tail"]


def test_missing_declared_file_is_red(tmp_path):
    """A declared file absent from the attempt is the one ``missing`` (A30)."""
    row = {"files": ["skills/a.py"], "targets": "`skills/test_gone.py::test_a`"}
    res = _check(_attempt(tmp_path, None, {}), row)
    assert (res["verdict"], res["reason"]) == ("FAIL", "red test (file-missing)"), res
