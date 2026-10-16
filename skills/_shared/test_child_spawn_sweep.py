"""Tests for child_spawn.py — the `sweep` subcommand.

strata-session-isolation task 3.2 (design §B6, detailed-design §CLI `sweep`): `sweep [--run R |
--stale]` answers exactly `{"stopped": [...], "gone": [...]}`. With `--run` (default
`$CLAUDE_CODE_SESSION_ID`) it stops every `running` child state in that run's dir and leaves any
other state (`done`) untouched; with `--stale` it walks every run dir of the repo's child-state
base and stops only a `running` state whose `deadline_at` (epoch seconds) is already past, so a
concurrent run's within-deadline child is never touched. A state whose recorded pid is no longer
that process is reported in `gone` and marked `gone`. Both paths go through `cmd_stop`, so the
inner agent reaches the stopped-agents file and the child's slot is released.

Every repo here is a real tmp repo built with `attempt_fixture`'s scrubbed git env and passed as
`--root`, so the run dirs land inside it and never the ambient repo, and the session env is always
monkeypatched so no test reads the real one. Each test launches its own
`python3 -c "import time; time.sleep(60)"` stand-in through `child_proc.launch` and, in its
`finally`, signals only that test's recorded pgid and reaps only that pid. Nothing names a process
for a kill tool to match and no real `claude`/router/GPU job starts; the two releasers are
monkeypatched on their own modules, so the red fails on the missing subcommand.
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
from attempt_fixture import commit, git  # noqa: E402

SLEEP_ARGV = [sys.executable, "-c", "import time; time.sleep(60)"]
CHILD_A = "aa11aa11-0000-4000-8000-00000000000a"
CHILD_B = "bb22bb22-0000-4000-8000-00000000000b"


def _inner(child: str) -> str:
    """The inner agent id recorded for a child session (only its shape matters here)."""
    return "inner-" + child[:8]


def _repo(tmp_path: Path) -> Path:
    """A real tmp repo with one commit, on branch `main`."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit(repo, {"README.md": "demo\n"}, "base")
    return repo


def _launch(tmp_path: Path) -> dict:
    rec = child_proc.launch(SLEEP_ARGV, cwd=str(tmp_path),
                            out_path=str(tmp_path / "out.txt"), env=os.environ.copy())
    assert "pid" in rec, rec
    return rec


def _write_state(run_dir: Path, child: str, rec: dict, state: str = "running",
                 deadline: float | None = None) -> Path:
    data = {"child_session": child, "pid": rec["pid"], "pgid": rec["pgid"],
            "start_ticks": rec["start_ticks"], "inner_agent_id": _inner(child),
            "state": state}
    if deadline is not None:
        data["deadline_at"] = deadline
    path = run_dir / f"{child[:8]}.json"
    child_state.write(path, data)
    return path


def _reap(*recs: dict) -> None:
    """Signal and reap only the groups these tests started, so those pids are truly gone."""
    for rec in recs:
        try:
            os.killpg(rec["pgid"], signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            os.waitpid(rec["pid"], 0)
        except ChildProcessError:
            pass


def _no_proc() -> dict:
    """A pid/ticks pair that is not the recorded process — a `done` child has no live process."""
    return {"pid": os.getpid(), "pgid": os.getpid(), "start_ticks": -1}


def _patch_releasers(monkeypatch) -> tuple[list, list]:
    """Record the sweep's `append` / `release` calls instead of touching a router."""
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


def test_sweep_run_stops_running(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = _repo(tmp_path)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "envnotused")
    run = child_state.run_dir("runstop1", root=repo)
    rec = _launch(tmp_path)
    try:
        live = _write_state(run, CHILD_A, rec)
        # A `done` state is not a child to sweep: touching it would mark it `gone` and release a
        # slot it no longer holds.
        done = _write_state(run, CHILD_B, _no_proc(), state="done")
        appends, releases = _patch_releasers(monkeypatch)

        assert child_spawn.main(["sweep", "--run", "runstop1", "--root", str(repo)]) == 0
        assert _reply(capsys) == {"stopped": [CHILD_A], "gone": []}
        assert child_state.read(live)["state"] == "stopped"
        assert child_state.read(done)["state"] == "done"
        assert child_proc.alive(rec["pid"], rec["start_ticks"]) is False
        assert appends == [(_inner(CHILD_A), CHILD_A[:8])]
        assert releases == [(_inner(CHILD_A), CHILD_A)]
    finally:
        _reap(rec)


def test_sweep_default_run_from_env(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = _repo(tmp_path)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "runenv01")
    rec = _launch(tmp_path)
    try:
        live = _write_state(child_state.run_dir("runenv01", root=repo), CHILD_A, rec)
        other = child_state.run_dir("anotherrun", root=repo)
        other_state = _write_state(other, CHILD_B, _no_proc())
        _patch_releasers(monkeypatch)

        assert child_spawn.main(["sweep", "--root", str(repo)]) == 0
        assert _reply(capsys) == {"stopped": [CHILD_A], "gone": []}
        assert child_state.read(live)["state"] == "stopped"
        assert child_state.read(other_state)["state"] == "running"
    finally:
        _reap(rec)


def test_stale_stops_past_deadline_only(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = _repo(tmp_path)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    rec_a, rec_b = _launch(tmp_path), _launch(tmp_path)
    try:
        past = _write_state(child_state.run_dir("runstale", root=repo), CHILD_A, rec_a,
                            deadline=time.time() - 60)
        fresh = _write_state(child_state.run_dir("runfresh", root=repo), CHILD_B, rec_b,
                             deadline=time.time() + 3600)
        _patch_releasers(monkeypatch)

        assert child_spawn.main(["sweep", "--stale", "--root", str(repo)]) == 0
        assert _reply(capsys) == {"stopped": [CHILD_A], "gone": []}
        assert child_state.read(past)["state"] == "stopped"
        assert child_state.read(fresh)["state"] == "running"
        assert child_proc.alive(rec_b["pid"], rec_b["start_ticks"]) is True
    finally:
        _reap(rec_a, rec_b)


def test_stale_marks_dead_pid_gone(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = _repo(tmp_path)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    rec = _launch(tmp_path)
    _reap(rec)  # this test's own group only: the recorded pid is now truly gone
    try:
        path = _write_state(child_state.run_dir("rundeada", root=repo), CHILD_A, rec,
                            deadline=time.time() - 60)
        appends, releases = _patch_releasers(monkeypatch)

        assert child_spawn.main(["sweep", "--stale", "--root", str(repo)]) == 0
        assert _reply(capsys) == {"stopped": [], "gone": [CHILD_A]}
        assert child_state.read(path)["state"] == "gone"
        assert appends == [(_inner(CHILD_A), CHILD_A[:8])]
        assert releases == [(_inner(CHILD_A), CHILD_A)]
    finally:
        _reap(rec)
