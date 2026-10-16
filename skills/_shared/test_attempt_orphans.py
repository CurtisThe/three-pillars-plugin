"""Tests for attempt_orphans.py — open-request rule, status, stop record, hold time.

m44-orphan-reaper task 1.3: whether a stopped attempt still holds the GPU is
decided by router-log pairing (open = local request with no close yet), not by
the transcript alone. `open_local_requests` pairs a `route=local` request with
each close kind (stats, mid-response local reset, local unreachable,
`STOPPED-AGENT drop`), ignores fallback/upstream requests and other agents, and
pairs in log order (a close with nothing open is ignored). `status` is `done` on
end-of-turn or on a settled `stop_result` (`ok`/`gone`) with zero open requests. `mark_stopped` validates the result and stamps the state
file; `hold_seconds` spans start to the last close ts, or to `now` while open.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pytest  # noqa: E402

import router_stats as rs  # noqa: E402
import attempt_orphans as ao  # noqa: E402

CASES = json.loads((HERE / "fixtures" / "transcript_tail" / "tails.json").read_text(encoding="utf-8"))["cases"]
AGENT = "a0000001"
TS = {  # distinct stamps so hold_seconds can use the last close ts
    "req": "2026-10-01 10:00:00",
    "stats": "2026-10-01 10:00:05",
    "reset": "2026-10-01 10:00:10",
    "unreach": "2026-10-01 10:00:15",
    "drop": "2026-10-01 10:00:20",
}


def line(kind: str, agent: str = AGENT) -> str:
    """One synthetic router line per close/request kind (all parse, asserted below)."""
    if kind == "req":
        return f"[{TS['req']}] POST /v1/messages  model=qwen  sess=abcd1234  agent={agent}  -> local"
    if kind == "req_up":
        return f"[{TS['req']}] POST /v1/messages  model=qwen  sess=abcd1234  agent={agent}  -> upstream"
    if kind == "stats":
        return (f"[{TS['stats']}] LOCAL-STATS v=1 sess=abcd1234 agent={agent} model=m "
                "output_tokens=10 stop_reason=end_turn wall_s=1.0 clamped=0")
    if kind == "reset":
        return f"[{TS['reset']}] client-reset mid-response sess=abcd1234 agent={agent} route=local"
    if kind == "reset_idle":
        return f"[{TS['reset']}] client-reset idle sess=abcd1234 agent={agent} route=local"
    if kind == "unreach":
        return f"[{TS['unreach']}] UPSTREAM-UNREACHABLE route=local sess=abcd1234 agent={agent}"
    if kind == "drop":
        return f"[{TS['drop']}] STOPPED-AGENT drop sess=abcd1234 agent={agent} route=local"
    if kind == "refuse":
        return f"[{TS['drop']}] STOPPED-AGENT refuse sess=abcd1234 agent={agent} route=local"
    raise AssertionError(kind)


@pytest.mark.parametrize("kind", ["req", "req_up", "stats", "reset", "reset_idle", "unreach", "drop", "refuse"])
def test_synthetic_lines_parse(kind):
    assert rs.parse_line(line(kind)) is not None


def events(*kinds: str, agent: str = AGENT) -> list[dict]:
    out = []
    for k in kinds:
        ev = rs.parse_line(line(k, agent=agent))
        assert ev is not None
        out.append(ev)
    return out


def _transcript(tmp_path: Path, case: str) -> Path:
    path = tmp_path / "agent.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in CASES[case]) + "\n", encoding="utf-8")
    return path


def _cfg_agent(tmp_path: Path, case: str, agent: str = AGENT) -> Path:
    """The located transcript at `<config_dir>/projects/*/*/subagents/agent-<agent>.jsonl`."""
    sub = tmp_path / "projects" / "proj" / "sess" / "subagents"
    sub.mkdir(parents=True, exist_ok=True)
    (sub / f"agent-{agent}.jsonl").write_text(
        "\n".join(json.dumps(r) for r in CASES[case]) + "\n", encoding="utf-8")
    return tmp_path


# --- open_local_requests ------------------------------------------------------

def test_open_request_without_close_is_open():
    assert ao.open_local_requests(events("req"), AGENT) == 1


@pytest.mark.parametrize("close", ["stats", "reset", "unreach", "drop"])
def test_each_close_kind_pairs_the_request(close):
    assert ao.open_local_requests(events("req", close), AGENT) == 0


def test_refuse_and_idle_reset_are_not_closes():
    assert ao.open_local_requests(events("req", "refuse"), AGENT) == 1
    assert ao.open_local_requests(events("req", "reset_idle"), AGENT) == 1


def test_fallback_and_upstream_requests_ignored():
    assert ao.open_local_requests(events("req_up"), AGENT) == 0


def test_other_agents_ignored():
    assert ao.open_local_requests(events("req", agent="b0000002"), AGENT) == 0
    assert ao.open_local_requests(events("req"), "b0000002-rest") == 0


def test_floored_at_zero():
    assert ao.open_local_requests(events("stats", "stats", "drop", "unreach"), AGENT) == 0
    assert ao.open_local_requests([], AGENT) == 0


def test_close_before_any_open_in_window_is_ignored():
    # PR #221 r1: the first request is logged before `arm` records log_offset, so its
    # close is in the window with no open; it must not cancel the next open request.
    assert ao.open_local_requests(events("stats", "req"), AGENT) == 1
    assert ao.open_local_requests(events("req", "stats", "stats", "req"), AGENT) == 1


# --- status -------------------------------------------------------------------

def test_status_running_when_open_request(tmp_path):
    state = {"agent_id": AGENT, "log_offset": 0, "stop_result": "ok"}
    log = tmp_path / "router.log"
    log.write_text(line("req") + "\n", encoding="utf-8")
    out = ao.status(state, router_log=log)
    assert out["state"] == "running" and out["open_requests"] == 1


@pytest.mark.parametrize("result,expect", [("gone", "done"), ("ok", "done"),
                                           ("refused", "running"), ("error", "running")])
def test_status_settled_stop_with_nothing_open(tmp_path, result, expect):
    # PR #221 r1: `gone` is settled for the reaper (never retried), so it must also
    # release the GPU once nothing is open, or the phase holds the GPU forever.
    state = {"agent_id": AGENT, "log_offset": 0, "stop_result": result}
    log = tmp_path / "router.log"
    log.write_text("", encoding="utf-8")
    assert ao.status(state, config_dir=tmp_path / "cfg", router_log=log)["state"] == expect


def test_status_done_after_close_line(tmp_path):
    state = {"agent_id": AGENT, "log_offset": 0, "stop_result": "ok"}
    log = tmp_path / "router.log"
    log.write_text(line("req") + "\n" + line("stats") + "\n", encoding="utf-8")
    out = ao.status(state, router_log=log)
    assert out["state"] == "done" and out["open_requests"] == 0


def test_status_done_on_end_of_turn_regardless(tmp_path):
    cfg = _cfg_agent(tmp_path, "end_turn_trailing")
    state = {"agent_id": AGENT, "log_offset": 0, "stop_result": "refused"}
    out = ao.status(state, config_dir=cfg, router_log=tmp_path / "absent.log")
    assert out["state"] == "done"


def test_status_ignores_events_before_log_offset(tmp_path):
    log = tmp_path / "router.log"
    log.write_text(line("req") + "\n", encoding="utf-8")
    offset = log.stat().st_size  # the first request sits before the offset
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(line("req") + "\n")  # only this one is after it
    state = {"agent_id": AGENT, "log_offset": offset, "stop_result": "ok"}
    assert ao.status(state, router_log=log)["open_requests"] == 1


def test_status_missing_router_log_never_raises(tmp_path):
    state = {"agent_id": AGENT, "log_offset": 0, "stop_result": "ok"}
    assert ao.status(state, router_log=tmp_path / "no" / "such.log")["open_requests"] == 0


# --- orphan_finished ----------------------------------------------------------

def test_orphan_finished_follows_transcript(tmp_path):
    cfg = _cfg_agent(tmp_path, "mid_tool_call")
    assert ao.orphan_finished({"agent_id": AGENT}, cfg) is False
    cfg = _cfg_agent(tmp_path, "end_turn_trailing")
    assert ao.orphan_finished({"agent_id": AGENT}, cfg) is True


def test_orphan_finished_no_transcript_is_false(tmp_path):
    assert ao.orphan_finished({"agent_id": AGENT}, tmp_path) is False


# --- mark_stopped -------------------------------------------------------------

def _base_state() -> dict:
    return {"attempt_id": "1.3", "agent_id": AGENT, "orphan": True, "note": "keep-me"}


def test_mark_stopped_ok(tmp_path):
    path = tmp_path / "w.json"
    path.write_text(json.dumps(_base_state()) + "\n", encoding="utf-8")
    out = ao.mark_stopped(path, result="ok", now=123.0)
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert out == on_disk
    assert out["stop_result"] == "ok" and out["stopped_at"] == 123.0
    assert out["stop_attempts"] == 1
    assert out["attempt_id"] == "1.3" and out["agent_id"] == AGENT
    assert out["orphan"] is True and out["note"] == "keep-me"


def test_mark_stopped_increments_and_keeps_keys(tmp_path):
    path = tmp_path / "w.json"
    path.write_text(json.dumps({**_base_state(), "stop_attempts": 2}) + "\n", encoding="utf-8")
    out = ao.mark_stopped(path, result="error", now=456.0)
    assert out["stop_attempts"] == 3 and out["stopped_at"] == 456.0
    assert json.loads(path.read_text(encoding="utf-8"))["stop_attempts"] == 3


def test_mark_stopped_bad_result_raises_before_write(tmp_path):
    path = tmp_path / "w.json"
    path.write_text(json.dumps(_base_state()) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        ao.mark_stopped(path, result="maybe", now=1.0)
    assert json.loads(path.read_text(encoding="utf-8")) == _base_state()


# --- hold_seconds -------------------------------------------------------------

def test_hold_seconds_closed_request_uses_last_close_ts():
    start = rs.ts_epoch("2026-10-01 10:00:00")
    end = rs.ts_epoch("2026-10-01 10:00:05")
    evs = events("req", "stats")
    assert ao.hold_seconds({"agent_id": AGENT, "stopped_at": start}, evs, now=10_000_000.0) == end - start


def test_hold_seconds_open_request_ends_at_now():
    start = rs.ts_epoch("2026-10-01 10:00:00")
    evs = events("req")
    assert ao.hold_seconds({"agent_id": AGENT, "orphaned_at": start}, evs, now=1_000_000.0) == 1_000_000.0 - start


def test_hold_seconds_without_start_is_none():
    assert ao.hold_seconds({}, events("req"), now=100.0) is None



def test_hold_seconds_without_a_later_close_ends_at_the_stop():
    """Audit M3: nothing open and no close after the start -> the hold ends at
    the stop time (else 0), never at `now`."""
    start = rs.ts_epoch("2026-10-01 11:00:00")
    state = {"agent_id": AGENT, "orphaned_at": start, "stopped_at": start + 30}
    assert ao.hold_seconds(state, [], now=10_000_000.0) == 30
    assert ao.hold_seconds(state, events("req", "stats"), now=10_000_000.0) == 30  # close before start
    assert ao.hold_seconds({"agent_id": AGENT, "orphaned_at": start}, [], now=10_000_000.0) == 0


def test_hold_seconds_null_orphaned_at_falls_back_to_stopped_at():
    start = rs.ts_epoch("2026-10-01 10:00:00")
    evs = events("req", "stats")
    state = {"agent_id": AGENT, "orphaned_at": None, "stopped_at": start}
    assert ao.hold_seconds(state, evs, now=10_000_000.0) == 5
