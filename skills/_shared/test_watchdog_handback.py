"""test_watchdog_handback.py — a subagent's hand-back ends its turn; its trailing reset is no runaway.

design: run-throughput (seat live check 1, bugs B1 and B2; PR #178 fix pass)

Fixtures are scrubbed copies of the live check's own files: `handback.jsonl` keeps the
record shape of a 2.1.285 subagent transcript that ended with `SubagentHandback` (its
tool_result flagged `toolEndsTurn`); `handback_reset.log` keeps that agent's router
LOCAL-STATS lines and the `client-reset mid-response` logged as the stream closed.
B2: `end_of_turn` saw no `end_turn` stop and kept polling to the ceiling. B1: the
trailing reset was classed `runaway: generation client-reset mid-response`, discarding a
green commit. A completed agent is also no orphan holding the GPU (report item 3).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import attempt_watchdog as aw
import router_stats as rs
import transcript_tail as tt

FIX = Path(__file__).resolve().parent / "fixtures"
TRANSCRIPT = FIX / "transcript_tail" / "handback.jsonl"
LOG = FIX / "attempt_watchdog" / "handback_reset.log"
AGENT = "a0000009-handback"
CFG = {"attempt_wall_clock_s": 1200}
END = datetime.fromisoformat("2026-09-28T16:00:08.995+00:00").timestamp()


def _events(lines=None) -> list[dict]:
    lines = LOG.read_text(encoding="utf-8").splitlines() if lines is None else lines
    return [ev for ev in (rs.parse_line(line) for line in lines) if ev]


def _state(tmp_path) -> dict:
    return aw.arm(tmp_path / "w.json", attempt_id="t99", agent_id=AGENT, rung="local-xhigh",
                  phase="1", router_log=None, now=END - 30)


def test_handback_is_end_of_turn_with_its_message_as_reply():
    final = tt.end_of_turn(tt.read_records(TRANSCRIPT))
    assert final is not None
    assert final["text"] == "Task 9.9 done, green (scrubbed)"
    assert final["ts_last"] == "2026-09-28T16:00:08.995Z"


def test_handback_needs_the_toolendsturn_flag(tmp_path):
    recs = tt.read_records(TRANSCRIPT)
    recs[-1] = {k: v for k, v in recs[-1].items() if k != "toolEndsTurn"}
    assert tt.end_of_turn(recs) is None
    more = tt.read_records(TRANSCRIPT) + [{"type": "user", "message": {"content": "again"}}]
    assert tt.end_of_turn(more) is None  # a user record after the hand-back: still working


def test_poll_sees_the_handback_and_the_trailing_reset_is_not_a_runaway(tmp_path):
    out = aw.verdict(_state(tmp_path), TRANSCRIPT, _events(), CFG, END + 5)
    assert out["state"] == "done", out
    assert out["reply_text"] == "Task 9.9 done, green (scrubbed)"
    assert out["served"]["local_requests"] == 9


def test_finished_notification_excuses_a_trailing_reset_without_a_transcript(tmp_path):
    out = aw.verdict(_state(tmp_path), None, _events(), CFG, END + 5, finished=True)
    assert out["state"] == "done", out


def test_a_silent_reset_while_still_working_is_a_runaway_past_the_grace_window(tmp_path):
    recs = tt.read_records(TRANSCRIPT)[:-1]  # the hand-back not yet answered
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    reset_at = rs.ts_epoch("2026-09-28 10:06:14")
    early = aw.verdict(_state(tmp_path), path, _events(), CFG, reset_at + 5)
    assert early["state"] == "running"  # M48: one dropped stream is not yet a runaway
    out = aw.verdict(_state(tmp_path), path, _events(), CFG, reset_at + rs.RESET_GRACE_S)
    assert out["state"] == "runaway"
    assert out["reason"].startswith("runaway: generation client-reset mid-response")


def test_a_reset_answered_by_more_requests_is_not_a_runaway(tmp_path):
    lines = LOG.read_text(encoding="utf-8").splitlines()
    out = aw.verdict(_state(tmp_path), TRANSCRIPT, _events(lines + lines[-2:-1]), CFG, END + 5)
    assert out["state"] == "done", out  # M48: the reset was one slow stream


def test_completed_orphan_no_longer_holds_the_gpu(tmp_path):
    cfg = tmp_path / "cfg"
    sub = cfg / "projects" / "p" / "s" / "subagents"
    sub.mkdir(parents=True)
    (sub / f"agent-{AGENT}.jsonl").write_bytes(TRANSCRIPT.read_bytes())
    ladder = tmp_path / "ladder"
    aw.arm(ladder / "9.9.watch.json", attempt_id="t99", agent_id=AGENT, rung="local-xhigh",
           phase="1", router_log=None, now=END - 30)
    aw.mark_orphan(ladder / "9.9.watch.json")
    got = aw.orphans(ladder, phase="1", config_dir=cfg)
    assert got["holds_gpu"] is False and got["orphans"][0]["state"] == "done"
