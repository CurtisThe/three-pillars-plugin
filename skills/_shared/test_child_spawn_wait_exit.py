"""`child_spawn.py wait` exit codes: 0 done, 4 still running, 3 failed (reaper-false-worker-done).

A failed child answers exit 3 with its `why` on every reply, and a wait loop that follows the
documented snippet (break on `state != "running"`, capped by the deadline) ends on it.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import child_spawn  # noqa: E402
import child_state  # noqa: E402


def _wait(state_path, capsys, budget="0"):
    code = child_spawn.main(["wait", "--state", str(state_path), "--budget-s", budget])
    return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def _state(tmp_path, **extra):
    path = tmp_path / "c1.json"
    child_state.write(path, {"child_session": "c1", "pid": 0, "start_ticks": 1, **extra})
    return path


def test_failed_child_is_exit_3_with_why_on_every_reply(tmp_path, capsys):
    path = _state(tmp_path, state="failed", why="deadline")
    for _ in range(2):
        code, res = _wait(path, capsys)
        assert (code, res) == (3, {"state": "failed", "why": "deadline"})


def test_done_child_is_exit_0(tmp_path, capsys):
    path = _state(tmp_path, state="done", reply_path="r.txt")
    assert _wait(path, capsys) == (0, {"state": "done", "reply_path": "r.txt"})


def test_running_past_budget_is_exit_4(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(child_spawn.child_proc, "alive", lambda pid, ticks: True)
    path = _state(tmp_path, state="running", inner_agent_id="", deadline_at=time.time() + 600)
    assert _wait(path, capsys) == (4, {"state": "running"})


def test_documented_wait_loop_terminates_on_a_failed_child(tmp_path, capsys):
    """The child-spawn.md loop: break on `state != "running"`, never on the exit code alone."""
    path = _state(tmp_path, state="failed", why="deadline")
    calls = 0
    for _ in range(50):  # the cap: the child's deadline bounds the real loop
        calls += 1
        _, res = _wait(path, capsys)
        if res["state"] != "running":
            break
    assert calls == 1 and res["why"] == "deadline"
