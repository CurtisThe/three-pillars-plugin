"""Tests for the live-child check in attempt_reaper.watch (reaper-false-worker-done).

A tp-worker that ended its turn while a Strata child-session attempt still runs is not done:
(a) end of turn + a `running` child state with a live pid -> not done; (b) the child ended
-> done; (c) a dead pid with a stale `running` record -> done, the record left alone for
`child_spawn.py sweep`; (d) the in-process path (no child state dir) is unchanged. A state dir
that cannot be listed keeps the watch going, never a false done.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import attempt_reaper as ar  # noqa: E402
import attempt_reaper_children as arc  # noqa: E402
import child_proc  # noqa: E402

CASES = json.loads((HERE / "fixtures" / "transcript_tail" / "tails.json").read_text(encoding="utf-8"))["cases"]
WORKER = "w9876543"
SLUG = "demo"


def _worker_ended(tmp_path: Path) -> Path:
    sub = tmp_path / "cfg" / "projects" / "proj" / "sess" / "subagents"
    sub.mkdir(parents=True)
    (sub / f"agent-{WORKER}.jsonl").write_text(
        "\n".join(json.dumps(r) for r in CASES["end_turn_trailing"]) + "\n", encoding="utf-8")
    return tmp_path / "cfg"


def _ladder(tmp_path: Path) -> Path:
    lad = tmp_path / "common" / "tp-ladder" / SLUG
    lad.mkdir(parents=True)
    return lad


def _child(tmp_path: Path, name: str, *, state="running", pid=None, ticks_delta=0, slug=SLUG) -> Path:
    run = tmp_path / "common" / "tp-children" / "abcd1234"
    run.mkdir(parents=True, exist_ok=True)
    pid = os.getpid() if pid is None else pid
    path = run / f"{name}.json"
    path.write_text(json.dumps({
        "state": state, "pid": pid, "start_ticks": child_proc.start_ticks(pid) + ticks_delta,
        "cwd": str(tmp_path / ".tp-scratch" / f"tp-attempt-{slug}-1.4-abc")}), encoding="utf-8")
    return path


def _watch(lad, cfg):
    return ar.watch(lad, worker_agent_id=WORKER, for_s=0, config_dir=str(cfg))


def test_live_child_keeps_worker_not_done(tmp_path):
    cfg, lad = _worker_ended(tmp_path), _ladder(tmp_path)
    _child(tmp_path, "c1")
    assert _watch(lad, cfg) == {"reap": [], "worker_done": False, "for_s": 0}


def test_ended_child_is_done(tmp_path):
    cfg, lad = _worker_ended(tmp_path), _ladder(tmp_path)
    _child(tmp_path, "c1", state="done")
    assert _watch(lad, cfg)["worker_done"] is True


def test_dead_pid_with_stale_running_record_is_done_and_left_alone(tmp_path):
    cfg, lad = _worker_ended(tmp_path), _ladder(tmp_path)
    rec = _child(tmp_path, "c1", ticks_delta=1)  # a reused pid: different start ticks
    before = rec.read_text(encoding="utf-8")
    assert _watch(lad, cfg)["worker_done"] is True
    assert rec.read_text(encoding="utf-8") == before


def test_in_process_path_unchanged_without_child_dir(tmp_path):
    cfg, lad = _worker_ended(tmp_path), _ladder(tmp_path)
    assert _watch(lad, cfg)["worker_done"] is True


def test_other_designs_child_does_not_hold_this_watch(tmp_path):
    cfg, lad = _worker_ended(tmp_path), _ladder(tmp_path)
    _child(tmp_path, "c1", slug="other-design")
    assert _watch(lad, cfg)["worker_done"] is True


def test_ladder_outside_tp_ladder_has_no_child_dir(tmp_path):
    assert arc.children_base(tmp_path / "ladder") is None
    assert arc.live_child(tmp_path / "ladder") is False


def test_unlistable_state_dir_is_not_done(tmp_path, monkeypatch):
    lad = _ladder(tmp_path)
    _child(tmp_path, "c1", state="done")
    real = Path.iterdir

    def boom(self):
        if self.name == "tp-children":
            raise PermissionError("denied")
        return real(self)

    monkeypatch.setattr(Path, "iterdir", boom)
    assert arc.live_child(lad) is True
