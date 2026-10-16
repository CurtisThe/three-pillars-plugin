"""Tests for router_stats.py — the LOCAL-STATS v1 parser (run-throughput 1.3).

The fixture holds literal lines from local-llm-skills (`tests/test_local_stats.py`
L229-233, `tests/test_client_reset.py` L180-183), one live line from the 2026-09-28
soak, a non-stats REFUSE line and a torn last line.
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import router_stats as rs  # noqa: E402

LOG = HERE / "fixtures" / "router_stats" / "router.log"
LINES = LOG.read_text(encoding="utf-8").split("\n")
AGENT = "a0000001-rest-of-id"


def _events():
    return [e for e in (rs.parse_line(line) for line in LINES) if e]


def test_parse_stats_line_fields():
    ev = rs.parse_line(LINES[0])
    assert ev == {"kind": "stats", "ts": "2026-09-28 10:00:09", "sess": "aaaa1111",
                  "agent": "a0000001", "model": "qwen-local", "output_tokens": 24576,
                  "stop_reason": "max_tokens", "wall_s": 812.40, "clamped": 1}


def test_additive_field_is_ignored():
    ev = rs.parse_line(LINES[2])
    assert ev["kind"] == "stats" and ev["stop_reason"] == "tool_use"
    assert "extra" not in ev and ev["clamped"] == 0


def test_parse_reset_line_fields():
    ev = rs.parse_line(LINES[7])
    assert ev == {"kind": "reset", "ts": "2026-09-28 10:00:03", "mode": "mid-response",
                  "sess": "aaaa1111", "agent": "a0000001", "route": "local"}


def test_live_soak_line_parses():
    ev = rs.parse_line(LINES[10])
    assert ev["model"] == "qwen3.8-27b-240k" and ev["output_tokens"] == 3276
    assert ev["agent"] == "-" and ev["wall_s"] == 24.31


@pytest.mark.parametrize("line", [LINES[4], LINES[5], LINES[11], "", "garbage", None, 42])
def test_unmatched_lines_are_none(line):
    assert rs.parse_line(line) is None


def test_kinds_and_counts():
    kinds = [e["kind"] for e in _events()]
    assert kinds.count("stats") == 5 and kinds.count("reset") == 4


def test_for_agent_matches_8_char_prefix_and_never_dash():
    mine = rs.for_agent(_events(), AGENT)
    assert {e["agent"] for e in mine} == {"a0000001"}
    assert len(mine) == 4
    assert rs.for_agent(_events(), "-") == []
    assert rs.for_agent(_events(), "") == []


def test_runaway_event_on_max_tokens_and_mid_response_local():
    events = _events()
    first = rs.runaway_event(events)
    assert first["kind"] == "stats" and first["stop_reason"] == "max_tokens"
    resets = [e for e in events if e["kind"] == "reset"]
    assert rs.runaway_event(resets) is None  # no clock: a lone reset is never a breach (M48)
    hit = rs.runaway_event(resets, now=rs.ts_epoch("2026-09-28 10:00:03") + rs.RESET_GRACE_S)
    assert hit["mode"] == "mid-response" and hit["route"] == "local" and hit["after"] == "silent"


def test_runaway_event_ignores_idle_upstream_error_and_v2():
    benign = [rs.parse_line(LINES[i]) for i in (1, 2, 3, 6, 8, 9, 10)]
    assert {e["mode"] for e in benign if e["kind"] == "reset"} == {"idle", "mid-response"}
    assert rs.runaway_event(benign) is None
    err = rs.parse_line("[2026-09-28 10:00:20] LOCAL-STATS v=1 sess=aaaa1111 agent=a0000001 "
                        "model=qwen-local output_tokens=7 stop_reason=error wall_s=1.00 clamped=0")
    assert err["stop_reason"] == "error" and rs.runaway_event([err]) is None
    v2 = rs.parse_line(LINES[4])
    assert v2 is None


POST = ("[2026-09-30 03:48:40] POST /v1/messages  model=qwen3.8-27b-240k  sess=7e6f7258  "
        "agent=a65aeca7  effort=medium  -> local (model resident) owner=7e6f7258  (54214B)")
UNREACHABLE = ("[2026-09-30 04:42:50] UPSTREAM-UNREACHABLE route=local sess=7e6f7258 "
               "agent=a65aeca7 (timed out)")


def test_parse_request_and_unreachable_lines():
    assert rs.parse_line(POST) == {"kind": "request", "ts": "2026-09-30 03:48:40",
                                   "sess": "7e6f7258", "agent": "a65aeca7", "route": "local"}
    assert rs.parse_line(UNREACHABLE) == {"kind": "unreachable", "ts": "2026-09-30 04:42:50",
                                          "route": "local", "sess": "7e6f7258",
                                          "agent": "a65aeca7"}
    no_agent = POST.replace("agent=a65aeca7  ", "")
    assert rs.parse_line(no_agent)["agent"] == "-"
    assert rs.gen_stats([rs.parse_line(POST)])["local_requests"] == 0


def test_ts_epoch_unreadable_is_none():
    assert rs.ts_epoch("not a time") is None and rs.ts_epoch(None) is None


def test_runaway_event_max_gen_tokens_override():
    ev = rs.parse_line(LINES[1])
    assert rs.runaway_event([ev]) is None
    assert rs.runaway_event([ev], max_gen_tokens=500) is ev
    assert rs.runaway_event([ev], max_gen_tokens=1001) is None


def test_read_since_holds_back_torn_line(tmp_path):
    log = tmp_path / "router.log"
    log.write_bytes(LOG.read_bytes())
    events, offset = rs.read_since(log, 0)
    assert len(events) == 9
    assert offset == LOG.read_bytes().rindex(b"\n") + 1
    with open(log, "a", encoding="utf-8") as fh:
        fh.write("cal output_tokens=5 stop_reason=end_turn wall_s=0.10 clamped=0\n")
    more, offset2 = rs.read_since(log, offset)
    assert len(more) == 1 and more[0]["output_tokens"] == 5
    assert offset2 == log.stat().st_size
    assert rs.read_since(log, offset2) == ([], offset2)


def test_read_since_restarts_after_truncation(tmp_path):
    log = tmp_path / "router.log"
    log.write_text(LINES[1] + "\n", encoding="utf-8")
    events, offset = rs.read_since(log, 10_000)
    assert len(events) == 1 and offset == log.stat().st_size


def test_read_since_missing_file(tmp_path):
    assert rs.read_since(tmp_path / "absent.log", 123) == ([], 123)


def test_gen_stats_counts_stats_lines_only():
    stats = rs.gen_stats(rs.for_agent(_events(), AGENT))
    assert stats == {"local_requests": 2, "max": 24576, "p50": 1000, "at_cap": 1}
    assert rs.gen_stats([]) == {"local_requests": 0, "max": None, "p50": None, "at_cap": 0}


def test_log_path_resolution(tmp_path):
    assert rs.log_path({"TP_LOCAL_LOG": "/x/r.log"}) == Path("/x/r.log")
    assert rs.log_path({"XDG_STATE_HOME": "/s", "HOME": "/h"}) == Path("/s/tp-local/router.log")
    assert rs.log_path({"HOME": "/h"}) == Path("/h/.local/state/tp-local/router.log")


def _sibling() -> Path | None:
    env = os.environ.get("TP_LOCAL_LLM_SKILLS")
    if env:
        return Path(env)
    try:
        common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=HERE,
                                capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return (HERE / common).resolve().parent.parent / "local-llm-skills"


@pytest.mark.parametrize("action", ["refuse", "drop"])
def test_parse_stopped_line_both_actions(action):
    line = (f"[2026-09-30 05:00:00] STOPPED-AGENT {action} sess=abcd1234 "
            "agent=a0000001 route=local")
    assert rs.parse_line(line) == {"kind": "stopped", "ts": "2026-09-30 05:00:00",
                                   "action": action, "sess": "abcd1234",
                                   "agent": "a0000001", "route": "local"}


def test_stopped_line_dash_fields_and_trailing_fields():
    line = ("[2026-09-30 05:00:01] STOPPED-AGENT refuse sess=- agent=- route=- "
            "extra=1 more=stuff")
    assert rs.parse_line(line) == {"kind": "stopped", "ts": "2026-09-30 05:00:01",
                                   "action": "refuse", "sess": "-", "agent": "-",
                                   "route": "-"}


def test_runaway_event_ignores_stopped():
    events = [rs.parse_line("[2026-09-30 05:00:00] STOPPED-AGENT refuse sess=abcd1234 "
                             "agent=a0000001 route=local"),
              rs.parse_line("[2026-09-30 05:00:01] STOPPED-AGENT drop sess=- agent=- "
                             "route=-")]
    assert rs.runaway_event(events) is None


def test_day_of():
    assert rs.day_of("2026-10-01T14:03:22") == "2026-10-01"
    assert rs.day_of("2026-10-01 14:03:22.123") == "2026-10-01"
    assert rs.day_of("not a time") is None and rs.day_of(None) is None and rs.day_of(42) is None


def test_daily_counts_local_mid_resets_and_stops():
    events = [
        rs.parse_line("[2026-10-01 09:00:00] client-reset mid-response sess=a agent=a route=local"),
        rs.parse_line("[2026-10-01 10:00:00] client-reset mid-response sess=a agent=a route=remote"),
        rs.parse_line("[2026-10-01 11:00:00] client-reset idle sess=a agent=a route=local"),
        rs.parse_line("[2026-10-01 12:00:00] STOPPED-AGENT refuse sess=a agent=a route=local"),
        rs.parse_line("[2026-10-01 13:00:00] STOPPED-AGENT drop sess=a agent=a route=local"),
        rs.parse_line("[2026-10-02 09:00:00] STOPPED-AGENT refuse sess=a agent=a route=local"),
        rs.parse_line("[2026-10-02 10:00:00] LOCAL-STATS v=1 sess=a agent=a model=m "
                      "output_tokens=5 stop_reason=end_turn wall_s=1.00 clamped=0"),
        rs.parse_line("[garbage] client-reset mid-response sess=a agent=a route=local"),
    ]
    assert rs.daily_counts(events) == {
        "2026-10-01": {"reset_local_mid": 1, "stopped_refuse": 1, "stopped_drop": 1},
        "2026-10-02": {"reset_local_mid": 0, "stopped_refuse": 1, "stopped_drop": 0},
    }
    assert rs.daily_counts([]) == {}
    undated = [rs.parse_line("[garbage] STOPPED-AGENT refuse sess=a agent=a route=local")]
    assert rs.daily_counts(undated) == {}


def test_contract_drift_against_sibling_local_stats():
    sibling = _sibling()
    src = sibling / "bin" / "local_stats.py" if sibling else None
    if src is None or not src.is_file():
        pytest.skip("local-llm-skills sibling checkout absent")
    tree = ast.parse(src.read_text(encoding="utf-8"))
    fields = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                  and any(getattr(t, "id", None) == "FIELDS" for t in n.targets))
    assert tuple(re.findall(r"(\w+)=", rs.STATS_RE.pattern)) == tuple(fields)
