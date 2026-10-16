"""Tests for child_proc.py — detached launch and /proc start ticks.

strata-session-isolation task 1.1: `launch` starts a child in its own session
(`start_new_session=True`), so the child's process group is exactly its pid —
the only group a later stop may signal — and reports pid / pgid / start ticks.
`start_ticks` reads field 22 of `/proc/<pid>/stat` (starttime in clock ticks),
which is how a stop proves a pid is still the process it recorded; `has_proc`
is false when `/proc` is missing. Every process here is a `python3 -c` stand-in
the test starts itself, and each test signals only the process group it started
(recorded pgid, `os.killpg` in a `finally`) — never a process by name.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import child_proc  # noqa: E402

SLEEP_ARGV = [sys.executable, "-c", "import time; time.sleep(30)"]


def _stop_own_group(pgid: int, pid: int) -> None:
    """Kill only the process group this test started, then reap the child."""
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass


def _launch(tmp_path: Path, argv: list[str] = SLEEP_ARGV) -> dict:
    return child_proc.launch(
        argv,
        cwd=str(tmp_path),
        out_path=str(tmp_path / "out.txt"),
        env=os.environ.copy(),
    )


def test_launch_new_session(tmp_path: Path) -> None:
    result = _launch(tmp_path)

    assert {"pid", "pgid", "start_ticks"} <= set(result)
    pid, pgid = result["pid"], result["pgid"]
    assert pid > 0
    assert pgid == pid == os.getpgid(pid)
    assert pgid != os.getpgrp()
    assert result["start_ticks"] > 0
    try:
        assert os.path.isdir(f"/proc/{pid}")
    finally:
        _stop_own_group(pgid, pid)


def test_start_ticks_matches_proc(tmp_path: Path) -> None:
    result = _launch(tmp_path)
    pid = result["pid"]
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as fh:
            stat_line = fh.read()
        field_22 = int(stat_line.rsplit(")", 1)[1].split()[19])
        assert child_proc.start_ticks(pid) == field_22
        assert result["start_ticks"] == field_22
    finally:
        _stop_own_group(result["pgid"], pid)


def test_start_ticks_absent_pid_is_none() -> None:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()  # reaped: /proc/<pid> is gone
    assert child_proc.start_ticks(proc.pid) is None


def test_has_proc_false_without_proc(tmp_path: Path, monkeypatch) -> None:
    assert child_proc.has_proc() is True
    monkeypatch.setattr(child_proc, "PROC_ROOT", str(tmp_path / "no-proc-here"))
    assert child_proc.has_proc() is False


def test_launch_failure_returns_error(tmp_path: Path) -> None:
    result = _launch(tmp_path, ["/nonexistent/bin"])
    assert "error" in result
    assert "pid" not in result
