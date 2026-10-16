"""test_ladder_live_orphan.py — a stopped W whose request still holds the GPU survives.

design: m44-orphan-reaper (Task 1.7). `clear_task` must keep a swept W that was
`stop_attempts: 1` (stopped, no `orphan` mark) while its `route=local` request in the
router log is still open, and must remove it once the close line (LOCAL-STATS) is
written. The router log is placed via `TP_LOCAL_LOG`; the agent transcript is absent,
so only the router log decides. Stdlib only; no `claude` calls.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import attempt_watchdog as aw  # noqa: E402
import ladder_files  # noqa: E402
import router_stats  # noqa: E402

AGENT = "a0000001"
SIDES = (".check.json", ".scan.json", ".reply.txt", ".watch.json", ".poll.json")

REQ_LINE = "[2026-10-01 10:00:00] POST /v1/messages  model=x  sess=abcd1234  agent=a0000001  -> local"
STATS_LINE = ("[2026-10-01 10:00:05] LOCAL-STATS v=1 sess=abcd1234 agent=a0000001 model=m "
              "output_tokens=10 stop_reason=end_turn wall_s=1.0 clamped=0")


def _task_files(ldir: Path, task: str) -> Path:
    """Prior-run side files for `task`; returns the W path."""
    (ldir / f"{task}.json").write_text(json.dumps({"task_id": task, "final": "done"}))
    for side in (".check.json", ".scan.json", ".poll.json"):
        (ldir / f"{task}{side}").write_text("{}\n")
    (ldir / f"{task}.reply.txt").write_text('{"claimed": "green"}\n')
    w = ldir / f"{task}.watch.json"
    aw.arm(w, attempt_id=f"demo/{task}-0bcad012", agent_id=AGENT,
           rung="local-medium", phase="1", router_log=None, now=0.0)
    return w


def _left(ldir: Path) -> set:
    return {p.name for p in ldir.iterdir()}


def test_router_lines_parse():
    assert router_stats.parse_line(REQ_LINE) is not None
    assert router_stats.parse_line(STATS_LINE) is not None


def test_stopped_w_with_open_request_survives_fresh_and_close_removes_it(tmp_path, monkeypatch):
    log = tmp_path / "router.log"
    monkeypatch.setenv("TP_LOCAL_LOG", str(log))
    ldir = tmp_path / "ladder"
    ldir.mkdir()
    w = _task_files(ldir, "1.7")
    # A stopped attempt: one stop recorded, not orphan-marked, log read from the start.
    state = json.loads(w.read_text(encoding="utf-8"))
    state.update(stop_result="ok", stop_attempts=1)
    w.write_text(json.dumps(state), encoding="utf-8")

    # (a) The request is still open -> the W survives; every other side file is removed.
    log.write_text(REQ_LINE + "\n", encoding="utf-8")
    out = ladder_files.clear_task(ldir, "1.7", config_dir=tmp_path)
    assert out["kept_orphans"] == [str(w)]
    assert w.exists()
    assert _left(ldir) == {"1.7.json", "1.7.watch.json"}

    # (b) The close line lands -> the W is gone.
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(STATS_LINE + "\n")
    out = ladder_files.clear_task(ldir, "1.7", config_dir=tmp_path)
    assert out["kept_orphans"] == []
    assert not w.exists()
    assert _left(ldir) == {"1.7.json"}


def test_plain_armed_w_is_removed(tmp_path, monkeypatch):
    monkeypatch.setenv("TP_LOCAL_LOG", str(tmp_path / "router.log"))
    ldir = tmp_path / "ladder"
    ldir.mkdir()
    w = _task_files(ldir, "1.7")
    (tmp_path / "router.log").write_text(REQ_LINE + "\n", encoding="utf-8")
    out = ladder_files.clear_task(ldir, "1.7", config_dir=tmp_path)
    assert out["kept_orphans"] == []
    assert not w.exists()
    assert _left(ldir) == {"1.7.json"}
