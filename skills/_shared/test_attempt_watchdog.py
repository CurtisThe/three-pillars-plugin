"""Tests for attempt_watchdog.py — arm, pure verdict, mark_orphan (run-throughput 1.5).

Injected `now` everywhere; no sleeping. The `done` cases read the real-tail
fixtures/transcript_tail/tails.json; the breach lines are hand-written in
fixtures/attempt_watchdog/breach.json. `verdict` applies `router_stats.for_agent`
itself — the tests pass whole-event lists, not pre-filtered ones.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import attempt_watchdog as aw  # noqa: E402
import router_stats as rs  # noqa: E402

BUNDLES = json.loads((HERE / "fixtures" / "attempt_watchdog" / "breach.json").read_text(encoding="utf-8"))
CASES = json.loads((HERE / "fixtures" / "transcript_tail" / "tails.json").read_text(encoding="utf-8"))["cases"]
AGENT = "a0000001-rest-of-id"
CFG = {"attempt_wall_clock_s": 1000}


def _state(tmp_path, started_at, log=None):
    """arm into tmp and return (state, state_path) with the given start clock."""
    path = tmp_path / "state" / "1.5.watch.json"
    state = aw.arm(path, attempt_id="t15", agent_id=AGENT, rung="local-medium",
                   phase="1", router_log=log, now=started_at)
    return json.loads(json.dumps(state)), path


def _transcript(tmp_path, case):
    path = tmp_path / "agent.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in CASES[case]) + "\n", encoding="utf-8")
    return path


def _events(bundle_key):
    return [ev for ev in (rs.parse_line(line) for line in BUNDLES[bundle_key]) if ev]


def _verdict(state, tmp_path, bundle=None, case=None, missing=False, now=100.0, **kw):
    if missing:
        transcript = tmp_path / "absent-agent.jsonl"  # a path that does not exist -> OSError
    else:
        transcript = _transcript(tmp_path, case) if case else None
    return aw.verdict(state, transcript, _events(bundle) if bundle else [], CFG, now, **kw)


def _end_epoch(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


FINAL_EPOCH = _end_epoch("2026-09-28T15:00:18.400Z")  # end_turn_trailing's final turn


# --- arm / mark_orphan ---------------------------------------------------------

def test_arm_shape_and_offsets(tmp_path):
    state, path = _state(tmp_path, 100.0)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"attempt_id": "t15", "agent_id": AGENT, "agent8": "a0000001",
                    "rung": "local-medium", "phase": "1", "started_at": 100.0,
                    "log_offset": 0, "orphan": False}
    assert state["log_offset"] == 0 and state["orphan"] is False


def test_arm_missing_log_offset_zero(tmp_path):
    assert aw.DEFAULT_WALL_S == 1200
    state = aw.arm(tmp_path / "w" / "watch.json", attempt_id="a", agent_id=AGENT,
                   rung="local", phase="1", router_log=tmp_path / "absent" / "router.log")
    assert state["log_offset"] == 0


def test_arm_records_the_lookback_offset_not_the_log_size(tmp_path):
    """`log_offset` is the first line within `ARM_LOOKBACK_S` before arm, not the log's size."""
    log = tmp_path / "router.log"
    older = BUNDLES["max_tokens"][0].replace("2026-09-28 10:00:09", "2026-09-28 09:00:00")
    log.write_text(older + "\n" + BUNDLES["end_turn"][0] + "\n", encoding="utf-8")
    now = _end_epoch("2026-09-28 10:00:09") + 100.0  # since 09:55:49 -> past `older`
    state, _ = _state(tmp_path, now, log=log)
    assert state["log_offset"] == len((older + "\n").encode("utf-8"))
    assert state["log_offset"] != log.stat().st_size


def test_mark_orphan(tmp_path):
    state, path = _state(tmp_path, 100.0)
    out = aw.mark_orphan(path)
    assert out["orphan"] is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["orphan"] is True and data["started_at"] == 100.0 and data["agent8"] == "a0000001"


# --- wall-clock rule -----------------------------------------------------------

def test_wall_clock_under_budget_is_running(tmp_path):
    state, _ = _state(tmp_path, 0.0)
    out = _verdict(state, tmp_path, now=999.0)
    assert out["state"] == "running" and out["reason"] == ""
    assert out["elapsed_s"] == 999.0
    assert out["flags"] == ["watchdog-no-router-stats"]


def test_wall_clock_at_budget_is_runaway(tmp_path):
    state, _ = _state(tmp_path, 0.0)
    out = _verdict(state, tmp_path, now=1000.0)
    assert out["state"] == "runaway"
    assert out["reason"] == "runaway: wall-clock 1000s ≥ 1000s"


def test_missing_transcript_running_then_runaway(tmp_path):
    state, _ = _state(tmp_path, 0.0)
    early = _verdict(state, tmp_path, missing=True, now=10.0)
    assert early["state"] == "running"
    assert "transcript missing" in early["error"]
    late = _verdict(state, tmp_path, missing=True, now=1000.0)
    assert late["state"] == "runaway"
    assert late["reason"].startswith("runaway: wall-clock")


# --- done ----------------------------------------------------------------------

def test_done_tail_read_late_is_done_not_runaway(tmp_path):
    start = FINAL_EPOCH - 100.0  # the fixture's final turn lands 100s after arm
    state, _ = _state(tmp_path, start)
    out = _verdict(state, tmp_path, case="end_turn_trailing", now=FINAL_EPOCH + 99_999.0)
    assert out["state"] == "done" and out["reason"] == ""
    assert out["reply_text"] == '{"claimed": "done"}'
    assert out["elapsed_s"] == 100.0
    assert out["served"]["turns"] == 2
    assert out["gen"] == {"local_requests": 0, "max": None, "p50": None, "at_cap": 0}
    assert "watchdog-no-router-stats" in out["flags"]


def test_done_counts_served_and_gen(tmp_path):
    state, _ = _state(tmp_path, FINAL_EPOCH - 60.0)
    out = _verdict(state, tmp_path, bundle="end_turn", case="end_turn_trailing", now=500.0)
    assert out["state"] == "done" and out["elapsed_s"] == 60.0
    assert out["served"] == {"local_requests": 1, "fallback_requests": 0, "turns": 2}
    assert out["gen"] == {"local_requests": 1, "max": 500, "p50": 500, "at_cap": 0}
    assert out["flags"] == []


# --- generation rule -----------------------------------------------------------

def test_stats_end_turn_for_agent_is_running(tmp_path):
    state, _ = _state(tmp_path, 0.0)
    out = _verdict(state, tmp_path, bundle="end_turn", now=100.0)
    assert out["state"] == "running" and out["reason"] == ""
    assert out["gen"] == {"local_requests": 1, "max": 500, "p50": 500, "at_cap": 0}


def test_max_tokens_for_agent_is_runaway(tmp_path):
    state, _ = _state(tmp_path, 0.0)
    out = _verdict(state, tmp_path, bundle="max_tokens", now=100.0)
    assert out["state"] == "runaway"
    assert out["reason"] == "runaway: generation stop_reason=max_tokens output_tokens=24576"


def test_max_tokens_for_another_agent_is_not_runaway(tmp_path):
    state, _ = _state(tmp_path, 0.0)
    out = _verdict(state, tmp_path, bundle="max_tokens_other", now=100.0)
    assert out["state"] == "running" and out["gen"]["local_requests"] == 0


def test_max_gen_tokens_override(tmp_path):
    state, _ = _state(tmp_path, 0.0)
    out = _verdict(state, tmp_path, bundle="big_end_turn", now=100.0, max_gen_tokens=500)
    assert out["state"] == "runaway"
    assert out["reason"] == "runaway: generation stop_reason=end_turn output_tokens=1000"


def test_mid_response_local_reset_is_runaway(tmp_path):
    state, _ = _state(tmp_path, 0.0)
    reset_at = rs.ts_epoch("2026-09-28 10:00:03")
    assert _verdict(state, tmp_path, bundle="mid_response_local", now=100.0)["state"] == "running"
    out = _verdict(state, tmp_path, bundle="mid_response_local", now=reset_at + rs.RESET_GRACE_S)
    assert out["state"] == "runaway"
    assert out["reason"] == ("runaway: generation client-reset mid-response, "
                             f"then no request for {rs.RESET_GRACE_S}s")
    assert out["gen"]["local_requests"] == 0


def test_idle_reset_is_not_runaway(tmp_path):
    state, _ = _state(tmp_path, 0.0)
    out = _verdict(state, tmp_path, bundle="idle", now=100.0)
    assert out["state"] == "running" and out["reason"] == ""


# --- offset / flag semantics ---------------------------------------------------

def test_pre_arm_lines_in_the_lookback_count_and_older_are_dropped(tmp_path):
    """`arm` reaches back `ARM_LOOKBACK_S`: a pre-arm line inside the window counts,
    one older than it stays behind the offset. `now` matches the fixture's real ts."""
    log = tmp_path / "router.log"
    older = BUNDLES["max_tokens"][0].replace("2026-09-28 10:00:09", "2026-09-28 09:00:00")
    log.write_text(older + "\n" + BUNDLES["end_turn"][0] + "\n", encoding="utf-8")
    state, _ = _state(tmp_path, _end_epoch("2026-09-28 10:00:09") + 100.0, log=log)
    events, _offset = rs.read_since(log, state["log_offset"])
    assert [e["output_tokens"] for e in events] == [500]  # 10:00:09, not the 09:00:00 line
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(BUNDLES["big_end_turn"][0] + "\n")
    events, offset2 = rs.read_since(log, state["log_offset"])
    assert [e["output_tokens"] for e in events] == [500, 1000]
    assert offset2 == log.stat().st_size


def test_no_router_stats_flag_and_wall_bound(tmp_path):
    state, _ = _state(tmp_path, 0.0)
    early = _verdict(state, tmp_path, now=10.0)
    assert early["flags"] == ["watchdog-no-router-stats"] and early["state"] == "running"
    late = _verdict(state, tmp_path, now=1000.0)
    assert late["state"] == "runaway" and late["flags"] == ["watchdog-no-router-stats"]


# --- finished -----------------------------------------------------------------

def test_finished_mid_tool_call_is_done_with_no_end_turn(tmp_path):
    state, _ = _state(tmp_path, 0.0)
    out = _verdict(state, tmp_path, case="mid_tool_call", now=999_999.0, finished=True)
    assert out["state"] == "done" and out["reason"] == ""
    assert "watchdog-no-end-turn" in out["flags"]
    assert out["served"]["turns"] == 1 and "reply_text" not in out


def test_finished_missing_transcript_is_done_with_flag(tmp_path):
    state, _ = _state(tmp_path, 0.0)
    out = _verdict(state, tmp_path, missing=True, now=999_999.0, finished=True)
    assert out["state"] == "done" and out["reason"] == ""
    assert "watchdog-no-transcript" in out["flags"]
    assert out["error"]


def test_finished_generation_breach_is_runaway(tmp_path):
    state, _ = _state(tmp_path, 0.0)
    out = _verdict(state, tmp_path, bundle="max_tokens", case="end_turn_trailing",
                   now=FINAL_EPOCH + 1_000_000.0, finished=True)
    assert out["state"] == "runaway"
    assert out["reason"] == "runaway: generation stop_reason=max_tokens output_tokens=24576"


def test_module_is_small():
    # 1.4 raises the pin to the plan's ceiling (≤330) before arming Claude rungs
    assert len((HERE / "attempt_watchdog.py").read_text(encoding="utf-8").splitlines()) <= 330
