"""test_task_verify_env_faults.py — environment faults are never scored as the task's red.

design: local-implement-and-review (impl-audit-1 #2, #4)

A runner that cannot start (missing / not executable, rc 127 / 126) is an env-error
(exit 2), not a FAIL the ladder would retry and end Blocked. ``task_verify check`` and
the Tier 3.5 re-run share one run helper (``task_scope.run_capture``). Each attempt
commits the red/green pair (``commit_pair``). Real tmp repos only (``attempt_fixture``).
"""
from __future__ import annotations

import sys
from pathlib import Path

import task_attempts
import task_scope
import task_verify
from attempt_fixture import DD, commit_pair, make_seat, task_row

RUNNER = f"{sys.executable} -m pytest -q"
GREEN = "def test_a():\n    assert 1 == 1\n"
NODE_ROW = {"files": ["skills/a.py"], "targets": "`skills/test_a.py::test_a`"}


def _green_attempt(tmp_path: Path, task: str = "1.1") -> dict:
    _seat, wt = make_seat(tmp_path)
    att = task_attempts.open_attempt(wt, task, DD)
    commit_pair(Path(att["attempt_dir"]), {"skills/test_a.py": GREEN},
                {"skills/a.py": "A = 2\n"})
    return att


def test_missing_runner_is_env_error(tmp_path):
    att = _green_attempt(tmp_path)
    res = task_verify.check(att, task_row(**NODE_ROW), "tp-no-such-runner-xyz -m pytest",
                            rung="local", timeout=60)
    assert (res["verdict"], res["exit"]) == ("env-error", 2)
    assert res["reason"] == "runner-unavailable (rc 127)"
    assert "discard --attempt" in res["recover"]


def test_run_capture_maps_runner_faults(tmp_path):
    env = task_scope._git_env()
    assert task_scope.run_capture(["tp-no-such-runner-xyz"], tmp_path, 10, env=env,
                                  tail_chars=100)[0] == 127
    script = tmp_path / "not-exec.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    script.chmod(0o644)
    assert task_scope.run_capture([str(script)], tmp_path, 10, env=env,
                                  tail_chars=100)[0] == 126
    rc, _tail, timed_out = task_scope.run_capture(
        [sys.executable, "-c", "import time; time.sleep(5)"], tmp_path, 1, env=env,
        tail_chars=100)
    assert (rc, timed_out) == (None, True)
    assert task_scope.RUNNER_BROKEN_RCS == {126, 127}


def test_fallback_runner_is_python3(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    runner, source = task_scope.resolve_runner(tmp_path, None)
    assert runner == "python3 -m pytest" and source == "discovered"
    assert not runner.startswith("python ")


def test_red_at_base_error_keeps_pass(tmp_path, monkeypatch):
    """impl-audit-1 #4: red-at-base is evidence; its own git failure never halts a PASS."""
    import subprocess

    import task_verify_red_base

    def boom(*_a, **_k):
        raise subprocess.CalledProcessError(128, ["git", "worktree", "add"],
                                            stderr="fatal: boom\n")

    monkeypatch.setattr(task_verify_red_base, "red_at_base", boom)
    att = _green_attempt(tmp_path)
    res = task_verify.check(att, task_row(**NODE_ROW), RUNNER, rung="local", timeout=60)
    assert (res["verdict"], res["exit"], res["unverified"]) == ("PASS", 0, False)
    assert (res["red_at_base"], res["red_at_base_tail"]) == ("error", "fatal: boom")


# --- B3 (seat live check 1.1): a runner module missing from the interpreter -----------

def _python_without_pytest(tmp_path: Path) -> str:
    """A `python3` whose `-m pytest` fails exactly as the live dispatcher's did."""
    fake = tmp_path / "bin" / "python3"
    fake.parent.mkdir()
    fake.write_text('#!/bin/sh\necho "/usr/bin/python3: No module named pytest" >&2\nexit 1\n',
                    encoding="utf-8")
    fake.chmod(0o755)
    return f"{fake} -m pytest -q"


def test_missing_pytest_module_is_env_error_not_fail(tmp_path):
    att = _green_attempt(tmp_path)
    res = task_verify.check(att, task_row(**NODE_ROW), _python_without_pytest(tmp_path),
                            rung="local", timeout=60)
    assert (res["verdict"], res["exit"]) == ("env-error", 2)
    assert res["reason"] == "runner-unavailable (No module named pytest)"


def test_task_import_error_is_still_the_tasks_red(tmp_path):
    """The task's own missing import (a test's or a conftest's) is a FAIL, never env."""
    for name in ("skills/test_a.py", "skills/conftest.py"):
        sub = tmp_path / name.replace("/", "_")
        sub.mkdir()
        _seat, wt = make_seat(sub)
        att = task_attempts.open_attempt(wt, "1.1", DD)
        red, green = {"skills/test_a.py": GREEN}, {"skills/a.py": "A = 2\n"}
        into = red if name in red else green  # the red holds only the Targets file
        into[name] = "import tp_no_such_module_xyz\n" + into.get(name, "")
        commit_pair(Path(att["attempt_dir"]), red, green)
        res = task_verify.check(att, task_row(**NODE_ROW), RUNNER, rung="local", timeout=60)
        assert res["verdict"] == "FAIL" and res["exit"] == 1, (name, res["reason"])


def test_runner_broken_predicate():
    assert task_scope.runner_broken(127, "") == "rc 127"
    tail = "/usr/bin/python3: No module named pytest"
    assert task_scope.runner_broken(1, tail, "no-report") == "No module named pytest"
    quoted = "E   ModuleNotFoundError: No module named 'tp_x'"  # a conftest's: the task's
    assert task_scope.runner_broken(4, quoted, "no-report") is None
    assert task_scope.runner_broken(1, tail, "red") is None  # a report exists: the task's
    assert task_scope.runner_broken(0, tail, "no-report") is None
