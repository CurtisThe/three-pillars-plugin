"""test_task_verify_env_faults.py — environment faults are never scored as the task's red.

design: local-implement-and-review (impl-audit-1 #2, #4)

A runner that cannot start (missing / not executable, rc 127 / 126) is an env-error
(exit 2), not a FAIL the ladder would retry and end Blocked. ``task_verify check`` and
the Tier 3.5 re-run share one run helper (``task_scope.run_capture``). Real tmp repos
only (``attempt_fixture``).
"""
from __future__ import annotations

import sys
from pathlib import Path

import task_attempts
import task_scope
import task_verify
from attempt_fixture import DD, commit, make_seat, task_row

RUNNER = f"{sys.executable} -m pytest -q"
GREEN = "def test_a():\n    assert 1 == 1\n"
NODE_ROW = {"files": ["skills/a.py"], "targets": "`skills/test_a.py::test_a`"}


def _green_attempt(tmp_path: Path, task: str = "1.1") -> dict:
    _seat, wt = make_seat(tmp_path)
    att = task_attempts.open_attempt(wt, task, DD)
    commit(Path(att["attempt_dir"]), {"skills/a.py": "A = 2\n", "skills/test_a.py": GREEN})
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
    assert runner == "python3 -m pytest" and source == "pytest-config"
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
