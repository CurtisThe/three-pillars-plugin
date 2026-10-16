"""Tests for child_spawn.py — the `stop` subcommand.

strata-session-isolation task 3.1 (design §B6, detailed-design §CLI `stop`): `stop --state S`
signals only the process group the state file recorded (`child_proc.stop_group`, PID + start-ticks
verified), records the inner agent in the stopped-agents file, releases the child's router slot and
rewrites the state as `stopped` — or `gone` when the recorded pid's ticks changed, which proves the
pid is not the recorded child, so nothing is signalled. It always exits 0 with one JSON line and
never raises: a missing or empty state file is an `error: …` reply, not a traceback.

Each test launches its own `python3 -c "time.sleep(60)"` stand-in through `child_proc.launch` and
writes the state file with `child_state.write`; the `finally` signals only that test's recorded pgid
and reaps only that pid. Nothing here names a process for a kill tool to match, and no real `claude`,
router or GPU job is ever started: `stopped_agents.append` and `child_slot.release` are monkeypatched
on their own modules, so the red fails on the missing subcommand rather than on a missing attribute.
"""
from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import child_proc  # noqa: E402
import child_slot  # noqa: E402
import child_spawn  # noqa: E402
import child_state  # noqa: E402
import stopped_agents  # noqa: E402

SLEEP_ARGV = [sys.executable, "-c", "import time; time.sleep(60)"]
CHILD_SESSION = "ab12cd34-5678-49ab-8cde-000000000001"
CHILD8 = CHILD_SESSION[:8]
INNER = "inner-1"


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


def _launch(tmp_path: Path) -> dict:
    rec = child_proc.launch(SLEEP_ARGV, cwd=str(tmp_path),
                            out_path=str(tmp_path / "out.txt"), env=os.environ.copy())
    assert "pid" in rec, rec
    return rec


def _state_path(tmp_path: Path, rec: dict, ticks: int | None = None) -> Path:
    path = tmp_path / "state.json"
    child_state.write(path, {
        "child_session": CHILD_SESSION,
        "pid": rec["pid"],
        "pgid": rec["pgid"],
        "start_ticks": rec["start_ticks"] if ticks is None else ticks,
        "inner_agent_id": INNER,
        "state": "running",
    })
    return path


def _patch_releasers(monkeypatch) -> tuple[list, list]:
    """Record the stop's `append` / `release` calls instead of touching a router."""
    appends: list = []
    releases: list = []

    def fake_append(agent_id: str, *, attempt_id: str, **kw) -> str:
        appends.append((agent_id, attempt_id))
        return "written"

    def fake_release(inner_id: str, child: str, module=None) -> dict:
        releases.append((inner_id, child))
        return {"agent": "released", "session": "released"}

    monkeypatch.setattr(stopped_agents, "append", fake_append)
    monkeypatch.setattr(child_slot, "release", fake_release)
    return appends, releases


def _reply(capsys) -> dict:
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(lines) == 1, lines
    return json.loads(lines[0])


def test_stop_running(tmp_path: Path, monkeypatch, capsys) -> None:
    rec = _launch(tmp_path)
    pid, pgid, ticks = rec["pid"], rec["pgid"], rec["start_ticks"]
    path = _state_path(tmp_path, rec)
    appends, releases = _patch_releasers(monkeypatch)
    try:
        assert child_spawn.main(["stop", "--state", str(path)]) == 0
        assert _reply(capsys) == {"result": "ok"}
        assert _wait_gone(pid, ticks)
        assert child_state.read(path)["state"] == "stopped"
        assert appends == [(INNER, CHILD8)]
        assert releases == [(INNER, CHILD_SESSION)]
    finally:
        _cleanup(pgid, pid)


def test_stop_gone(tmp_path: Path, monkeypatch, capsys) -> None:
    rec = _launch(tmp_path)
    pid, pgid, ticks = rec["pid"], rec["pgid"], rec["start_ticks"]
    path = _state_path(tmp_path, rec, ticks=ticks + 1)  # a reused pid: never signalled
    appends, releases = _patch_releasers(monkeypatch)
    try:
        assert child_spawn.main(["stop", "--state", str(path)]) == 0
        assert _reply(capsys) == {"result": "gone"}
        assert child_proc.alive(pid, ticks) is True  # the real child is untouched
        assert child_state.read(path)["state"] == "gone"
        assert appends == [(INNER, CHILD8)]
        assert releases == [(INNER, CHILD_SESSION)]
    finally:
        _cleanup(pgid, pid)


def test_stop_missing_state(tmp_path: Path, monkeypatch, capsys) -> None:
    appends, releases = _patch_releasers(monkeypatch)
    missing = tmp_path / "nope.json"
    assert child_spawn.main(["stop", "--state", str(missing)]) == 0
    reply = _reply(capsys)
    assert reply["result"].startswith("error: ")
    assert not missing.exists()
    assert appends == []
    assert releases == []


def test_stop_null_ticks(tmp_path: Path, monkeypatch, capsys) -> None:
    """A state whose `start_ticks` is null (no /proc at launch) still replies, never raises."""
    rec = _launch(tmp_path)
    pid, pgid, ticks = rec["pid"], rec["pgid"], rec["start_ticks"]
    path = tmp_path / "state.json"
    child_state.write(path, {"child_session": CHILD_SESSION, "pid": pid, "pgid": pgid,
                             "start_ticks": None, "inner_agent_id": INNER, "state": "running"})
    _patch_releasers(monkeypatch)
    try:
        assert child_spawn.main(["stop", "--state", str(path)]) == 0
        reply = _reply(capsys)
        assert reply == {"result": "gone"}  # -1 ticks never match: nothing signalled
        assert child_proc.alive(pid, ticks) is True
    finally:
        _cleanup(pgid, pid)


def test_stop_no_inner_releases_session(tmp_path: Path, monkeypatch, capsys) -> None:
    """No inner agent yet: nothing goes to stopped-agents, but the child session's slot is released."""
    rec = _launch(tmp_path)
    pid, pgid = rec["pid"], rec["pgid"]
    _cleanup(pgid, pid)  # killed and reaped: the recorded pid is dead
    path = tmp_path / "state.json"
    child_state.write(path, {"child_session": CHILD_SESSION, "pid": pid, "pgid": pgid,
                             "start_ticks": rec["start_ticks"], "inner_agent_id": "",
                             "state": "running"})
    appends, releases = _patch_releasers(monkeypatch)
    assert child_spawn.main(["stop", "--state", str(path)]) == 0
    assert _reply(capsys) == {"result": "gone"}
    assert appends == []
    assert releases == [(None, CHILD_SESSION)]
