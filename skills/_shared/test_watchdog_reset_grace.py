"""test_watchdog_reset_grace.py — a `client-reset mid-response` alone is no runaway (M48).

design: none (just-do-it M48; evidence in completed-tp-designs/run-throughput/runaway-check-rerun.md
§FTP runaways, on the `tp/m44-live-check` branch)

Claude Code drops one slow stream and carries on, so a local reset breaches only when an
error follows it for that agent (`stop_reason=error`, or `UPSTREAM-UNREACHABLE`) or when no
request or LOCAL-STATS arrives within `router_stats.RESET_GRACE_S`. The lines are the
`reset_*` bundles in fixtures/attempt_watchdog/breach.json. `poll` reads a real log file
with an injected `now`; nothing sleeps.
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
GRACE = rs.RESET_GRACE_S
RESET_AT = rs.ts_epoch("2026-09-28 10:00:03")  # the reset line in every reset_* bundle
REASON = "runaway: generation client-reset mid-response"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(aw, "_sleep", lambda s: pytest.fail("poll slept"))


def _poll(tmp_path, lines, now, case="mid_tool_call", started_at=RESET_AT - 10):
    log = tmp_path / "router.log"
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    transcript = tmp_path / "agent.jsonl"
    transcript.write_text("\n".join(json.dumps(r) for r in CASES[case]) + "\n", encoding="utf-8")
    state = tmp_path / "ladder" / "1.1.watch.json"
    aw.arm(state, attempt_id="t11", agent_id=AGENT, rung="local-medium", phase="1",
           router_log=None, now=started_at)
    return aw.poll(state, root=tmp_path, transcript=transcript, router_log=log, for_s=0,
                   wall_s=3600, now=now, capability_path=tmp_path / "absent-cap.json")


def test_grace_window_sits_between_the_evidence_and_the_wall_budget():
    # FTP 2026-09-30: a healthy attempt's next request came <= 181 s after its reset, and the
    # next healthy LOCAL-STATS took a 222 s median; the window must also end before the budget.
    assert 222 < GRACE < aw.DEFAULT_WALL_S


def test_reset_then_normal_local_stats_polls_running(tmp_path):
    out = _poll(tmp_path, BUNDLES["reset_then_stats"], now=RESET_AT + 5 * GRACE)
    assert out["state"] == "running", out
    assert out["reason"] == "" and out["gen"]["local_requests"] == 1


def test_reset_then_error_line_polls_runaway(tmp_path):
    out = _poll(tmp_path, BUNDLES["reset_then_error"], now=RESET_AT + 1820)
    assert out["state"] == "runaway"
    assert out["reason"] == f"{REASON}, then stop_reason=error"


def test_reset_then_upstream_unreachable_polls_runaway(tmp_path):
    out = _poll(tmp_path, BUNDLES["reset_then_unreachable"], now=RESET_AT + 1820)
    assert out["state"] == "runaway"
    assert out["reason"] == f"{REASON}, then UPSTREAM-UNREACHABLE"


def test_reset_with_nothing_after_polls_runaway_past_the_grace_window(tmp_path):
    lines = BUNDLES["mid_response_local"]
    assert _poll(tmp_path, lines, now=RESET_AT + GRACE - 1)["state"] == "running"
    out = _poll(tmp_path, lines, now=RESET_AT + GRACE)
    assert out["state"] == "runaway"
    assert out["reason"] == f"{REASON}, then no request for {GRACE}s"


def test_a_request_inside_the_window_answers_the_reset(tmp_path):
    out = _poll(tmp_path, BUNDLES["reset_then_request"], now=RESET_AT + 5 * GRACE)
    assert out["state"] == "running", out


def test_another_agents_traffic_does_not_answer_the_reset(tmp_path):
    out = _poll(tmp_path, BUNDLES["reset_then_other_agent"], now=RESET_AT + GRACE)
    assert out["state"] == "runaway" and out["reason"].startswith(REASON)


def test_reset_after_the_final_record_still_polls_done(tmp_path):
    final = datetime.fromisoformat("2026-09-28T15:00:18.400+00:00").timestamp()
    stamp = datetime.fromtimestamp(final + 3).strftime("%Y-%m-%d %H:%M:%S")  # local, as the router
    line = f"[{stamp}] client-reset mid-response sess=aaaa1111 agent=a0000001 route=local"
    out = _poll(tmp_path, [line], now=final + 3 + 5 * GRACE, case="end_turn_trailing",
                started_at=final - 60)
    assert out["state"] == "done", out
    assert out["reply_text"]
