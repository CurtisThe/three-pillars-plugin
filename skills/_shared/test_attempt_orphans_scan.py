"""Tests for attempt_orphans.orphans — the candidate rule and the settle loop.

m44-orphan-reaper task 1.4: `orphans` scans a ladder dir's `*.watch.json` files
for orphan-marked or stopped attempts of the phase, counts each until it ends
(open local request or unfinished transcript), and — while any of them still
holds the GPU — re-checks every `interval_s`, up to `settle_s`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pytest  # noqa: E402

import router_stats as rs  # noqa: E402
import attempt_orphans as ao  # noqa: E402

ORPHAN = "a1111111"   # phase 1, orphan-marked, still running (no transcript)
STOPPED = "a2222222"  # phase 1, stopped non-orphan, counted while a request is open
PHASE2 = "a3333333"   # phase 2, orphan-marked, ignored for phase 1


def req_line(agent: str) -> str:
    return f"[2026-10-01 10:00:00] POST /v1/messages  model=qwen  sess=abcd1234  agent={agent}  -> local"


def close_line(agent: str) -> str:
    return (f"[2026-10-01 10:00:05] LOCAL-STATS v=1 sess=abcd1234 agent={agent} model=m "
            "output_tokens=10 stop_reason=end_turn wall_s=1.0 clamped=0")


@pytest.mark.parametrize("agent", [ORPHAN, STOPPED, PHASE2])
def test_lines_parse(agent):
    assert rs.parse_line(req_line(agent)) is not None
    assert rs.parse_line(close_line(agent)) is not None


def _w(ladder: Path, name: str, state: dict) -> None:
    (ladder / name).write_text(json.dumps(state) + "\n", encoding="utf-8")


def _ladder(tmp_path: Path, log_lines: list[str]) -> Path:
    ladder = tmp_path / "ladder"
    ladder.mkdir()
    _w(ladder, "orphan.watch.json",
       {"attempt_id": "1.1", "agent_id": ORPHAN, "phase": 1, "orphan": True, "log_offset": 0})
    _w(ladder, "stopped.watch.json",
       {"attempt_id": "1.2", "agent_id": STOPPED, "phase": 1,
        "stop_result": "ok", "stop_attempts": 1, "log_offset": 0})
    _w(ladder, "phase2.watch.json",
       {"attempt_id": "2.1", "agent_id": PHASE2, "phase": 2, "orphan": True, "log_offset": 0})
    (ladder / "unreadable.watch.json").write_text("not json at all", encoding="utf-8")
    (tmp_path / "router.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    return ladder


def _end_of_turn(tmp_path: Path, agent: str) -> None:
    """The agent's transcript under `config_dir` already shows its end of turn."""
    cases = json.loads((HERE / "fixtures" / "transcript_tail" / "tails.json")
                       .read_text(encoding="utf-8"))["cases"]
    sub = tmp_path / "projects" / "proj" / "sess" / "subagents"
    sub.mkdir(parents=True, exist_ok=True)
    (sub / f"agent-{agent}.jsonl").write_text(
        "\n".join(json.dumps(r) for r in cases["end_turn_trailing"]) + "\n", encoding="utf-8")


def _calls(start: float) -> dict:
    return {"t": [float(start)], "sleeps": 0}


def _clock_and_sleep(calls: dict, log: Path | None = None, close_agent: str | None = None,
                     on_sleep: int | None = None):
    def clock() -> float:
        return calls["t"][0]

    def sleep(s: float) -> None:
        calls["sleeps"] += 1
        calls["t"][0] += s
        if log is not None and close_agent is not None and calls["sleeps"] == on_sleep:
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(close_line(close_agent) + "\n")

    return clock, sleep


# --- candidate rule -------------------------------------------------------------

def test_scan_counts_orphan_and_stopped_ignores_other_phase(tmp_path):
    ladder = _ladder(tmp_path, [req_line(ORPHAN), req_line(STOPPED)])
    out = ao.orphans(ladder, phase=1, config_dir=tmp_path, router_log=tmp_path / "router.log")
    assert out["holds_gpu"] is True
    by_agent = {o["agent_id"]: o for o in out["orphans"]}
    assert set(by_agent) == {ORPHAN, STOPPED}  # phase 2 and unreadable files skipped
    assert by_agent[ORPHAN] == {"attempt_id": "1.1", "agent_id": ORPHAN, "state": "running",
                                "stopped": False, "open_requests": 1}
    assert by_agent[STOPPED] == {"attempt_id": "1.2", "agent_id": STOPPED, "state": "running",
                                 "stopped": True, "open_requests": 1}


def test_stopped_done_once_its_request_closes(tmp_path):
    ladder = _ladder(tmp_path, [req_line(STOPPED), close_line(STOPPED)])
    out = ao.orphans(ladder, phase=1, config_dir=tmp_path, router_log=tmp_path / "router.log")
    by_agent = {o["agent_id"]: o for o in out["orphans"]}
    assert by_agent[STOPPED] == {"attempt_id": "1.2", "agent_id": STOPPED, "state": "done",
                                 "stopped": True, "open_requests": 0}
    assert by_agent[ORPHAN]["state"] == "running"
    assert out["holds_gpu"] is True  # the running orphan still holds


def test_missing_ladder_dir_is_empty(tmp_path):
    out = ao.orphans(tmp_path / "no" / "such", phase=1, config_dir=tmp_path,
                     router_log=tmp_path / "router.log")
    assert out == {"holds_gpu": False, "orphans": []}


# --- settle loop ------------------------------------------------------------------

def test_settle_zero_scans_once_without_sleep(tmp_path):
    ladder = _ladder(tmp_path, [req_line(STOPPED)])
    calls = _calls(100.0)
    clock, sleep = _clock_and_sleep(calls)
    out = ao.orphans(ladder, phase=1, config_dir=tmp_path, router_log=tmp_path / "router.log",
                     settle_s=0, interval_s=15, clock=clock, sleep=sleep)
    assert out["holds_gpu"] is True and calls["sleeps"] == 0


def test_settle_rechecks_and_returns_early_when_close_appears(tmp_path):
    ladder = _ladder(tmp_path, [req_line(STOPPED)])
    _end_of_turn(tmp_path, ORPHAN)  # the orphan already ended: only the stopped one holds
    log = tmp_path / "router.log"
    calls = _calls(200.0)
    clock, sleep = _clock_and_sleep(calls, log=log, close_agent=STOPPED, on_sleep=2)
    out = ao.orphans(ladder, phase=1, config_dir=tmp_path, router_log=log,
                     settle_s=90, interval_s=15, clock=clock, sleep=sleep)
    assert out["holds_gpu"] is False
    by_agent = {o["agent_id"]: o for o in out["orphans"]}
    assert by_agent[ORPHAN]["state"] == "done" and by_agent[STOPPED]["state"] == "done"
    assert calls["sleeps"] == 2  # scan, sleep, scan, sleep (+close), scan -> done


def test_settle_gives_up_at_budget_while_still_holding(tmp_path):
    ladder = _ladder(tmp_path, [req_line(STOPPED)])
    calls = _calls(200.0)
    clock, sleep = _clock_and_sleep(calls)
    out = ao.orphans(ladder, phase=1, config_dir=tmp_path, router_log=tmp_path / "router.log",
                     settle_s=90, interval_s=15, clock=clock, sleep=sleep)
    assert out["holds_gpu"] is True
    # re-checks while (elapsed) + interval <= settle: at elapsed 0,15,30,45,60,75 the
    # condition holds (75+15<=90) -> 6 sleeps + 7 total scans; at elapsed 90 it stops
    assert calls["sleeps"] == 6
