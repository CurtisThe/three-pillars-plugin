"""Tests for child_proc.py — verified liveness and process-group stop.

strata-session-isolation task 2.1: `alive` proves a pid is still the recorded
process (same pid AND same /proc start ticks), and `stop_group` signals only the
process group it recorded — SIGTERM, then SIGKILL after `grace_s` — never a pid
whose ticks changed (a reused pid). Every child here is launched by the test
itself through `child_proc.launch`, and each test signals only that child's
recorded pgid (via `child_proc.stop_group` or `os.killpg` in a `finally`), then
reaps it with `os.waitpid`. Nothing here names a process for a kill tool to
match: `test_no_kill_by_name` scans the `child_*.py` sources for the forbidden
tool names, which this file builds from pieces so the rule stays greppable.
"""
from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import child_proc  # noqa: E402

SLEEP_ARGV = [sys.executable, "-c", "import time; time.sleep(30)"]
# argv[2] is the one-word body of a kill-by-name tool, assembled at runtime.
IGN_TERM_ARGV = [
    sys.executable,
    "-c",
    "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)",
]
FORBIDDEN_TOOLS = ("pk" + "ill", "kill" + "all", "pg" + "rep")


def _reap(pid: int) -> None:
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass


def _cleanup(pgid: int, pid: int) -> None:
    """Signal only the group this test started, then reap the child."""
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    _reap(pid)


def _wait_gone(pid: int, ticks: int, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not child_proc.alive(pid, ticks):
            return True
        time.sleep(0.05)
    return False


def _launch(tmp_path: Path, argv: list[str] = SLEEP_ARGV) -> dict:
    rec = child_proc.launch(argv, cwd=str(tmp_path), out_path=str(tmp_path / "out.txt"),
                            env=os.environ.copy())
    assert "pid" in rec, rec
    return rec


def test_alive_same_ticks(tmp_path: Path) -> None:
    rec = _launch(tmp_path)
    pid, ticks = rec["pid"], rec["start_ticks"]
    try:
        assert child_proc.alive(pid, ticks) is True
        assert child_proc.alive(pid, ticks + 1) is False
    finally:
        _cleanup(rec["pgid"], pid)


def test_stop_term_path(tmp_path: Path) -> None:
    rec = _launch(tmp_path)
    pid, pgid, ticks = rec["pid"], rec["pgid"], rec["start_ticks"]
    try:
        assert child_proc.stop_group(pid, pgid, ticks, grace_s=5) == "ok"
        assert _wait_gone(pid, ticks)
    finally:
        _cleanup(pgid, pid)


def test_stop_kill_path(tmp_path: Path) -> None:
    rec = _launch(tmp_path, IGN_TERM_ARGV)
    pid, pgid, ticks = rec["pid"], rec["pgid"], rec["start_ticks"]
    try:
        assert child_proc.stop_group(pid, pgid, ticks, grace_s=1) == "ok"
        assert _wait_gone(pid, ticks)
    finally:
        _cleanup(pgid, pid)


def test_reused_pid_not_signalled(tmp_path: Path, monkeypatch) -> None:
    rec = _launch(tmp_path)
    pid, pgid, ticks = rec["pid"], rec["pgid"], rec["start_ticks"]
    calls: list[tuple[int, int]] = []

    def _record(group: int, sig: int) -> None:
        calls.append((group, sig))

    monkeypatch.setattr(child_proc.os, "killpg", _record)
    try:
        assert child_proc.stop_group(pid, pgid, ticks + 1, grace_s=1) == "gone"
        assert calls == []
    finally:
        monkeypatch.undo()
        _cleanup(pgid, pid)


def test_dead_pid_gone(tmp_path: Path) -> None:
    rec = _launch(tmp_path)
    pid, pgid, ticks = rec["pid"], rec["pgid"], rec["start_ticks"]
    _cleanup(pgid, pid)  # killed and reaped: /proc/<pid> is gone
    assert child_proc.alive(pid, ticks) is False
    assert child_proc.stop_group(pid, pgid, ticks, grace_s=1) == "gone"


def test_bad_pgid_not_signalled(tmp_path: Path) -> None:
    """A pgid that is not the recorded pid (0 = the caller's own group) is refused unsignalled."""
    rec = _launch(tmp_path)
    pid, pgid, ticks = rec["pid"], rec["pgid"], rec["start_ticks"]
    try:
        assert child_proc.stop_group(pid, 0, ticks, grace_s=1) == "error: bad pgid"
        assert child_proc.stop_group(1, 1, ticks, grace_s=1) == "error: bad pgid"
        assert child_proc.alive(pid, ticks) is True
    finally:
        _cleanup(pgid, pid)


_DENY_LIST_HEAD = "DEFAULT_DENY = [\n"
_DENY_LIST_TAIL = "\n]\n"


def _scanned_text(path: Path) -> str:
    """`path`'s source, minus the `"Bash(<tool>*)"` literals inside `child_permissions.py`'s deny list.

    Those strings are the shipped `--disallowedTools` entries (strata-classifier-cost-followups
    §A1): they forbid the tool to a child and never run it. Only the exact deny-rule spelling is
    removed, only in that file, and only between `DEFAULT_DENY = [` and its closing `]`, so the
    same literal anywhere else there (an allow list, a comment) still fails the scan.
    """
    text = path.read_text(encoding="utf-8")
    if path.name == "child_permissions.py":
        start = text.index(_DENY_LIST_HEAD) + len(_DENY_LIST_HEAD)
        end = text.index(_DENY_LIST_TAIL, start)
        block = text[start:end]
        for tool in FORBIDDEN_TOOLS:
            block = block.replace(f'"Bash({tool}*)"', "")
        text = text[:start] + block + text[end:]
    return text


def test_no_kill_by_name() -> None:
    sources = sorted(HERE.glob("child_*.py"))
    assert sources
    for path in sources:
        text = _scanned_text(path)
        for tool in FORBIDDEN_TOOLS:
            assert tool not in text, f"{path.name} mentions {tool}"


def test_only_killpg_signals() -> None:
    """No `child_*.py` source (helpers included) kills by name or by bare pid.

    `os.killpg` on the recorded group is the one allowed signal call; a bare-pid `os.kill(` or a
    kill-by-name tool could reach a process the framework never started. `child_spawn_fixture.py`
    is scanned too: it signals nothing, so it needs no exclusion.
    """
    sources = sorted(p for p in HERE.glob("child_*.py") if not p.name.startswith("test_"))
    assert sources
    for path in sources:
        text = _scanned_text(path)
        for needle in FORBIDDEN_TOOLS + ("os.kill(",):
            assert needle not in text, f"{path.name} mentions {needle}"
