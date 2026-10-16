"""Tests for attempt_watchdog.py — served `fallback_requests` and any-phase orphans
(cheap-tier-local-routing 2.2).

`verdict(...)["served"]["fallback_requests"]` counts the agent's own `FALLBACK upstream`
POSTs (router_stats.REQUEST_RE captures the route), beside the LOCAL-STATS
`local_requests`; another agent's FALLBACK lines never count, and the key is always
present (0 when the agent has none). `orphans(dir, phase=None)` reports every phase's
orphans, the CLI `--phase any` maps to None, and a concrete phase still filters.
The router lines are built in this file in the shapes of fixtures/router_stats/*.log.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import attempt_watchdog as aw  # noqa: E402
import router_stats as rs  # noqa: E402

CASES = json.loads((HERE / "fixtures" / "transcript_tail" / "tails.json").read_text(encoding="utf-8"))["cases"]
AGENT = "a0000001-rest-of-id"
OTHER = "b0000002"
CFG = {"attempt_wall_clock_s": 1000}


def _post(sec: int, agent8: str, route: str) -> str:
    tail = "local (model resident) owner=aaaa1111" if route == "local" \
        else "FALLBACK upstream (slot held by 0b0e0b0e)"
    return (f"[2026-09-28 10:00:{sec:02d}] POST /v1/messages  model=qwen-local  sess=aaaa1111"
            f"  agent={agent8}  effort=medium  -> {tail}  (5785B)")


def _stats(sec: int, agent8: str) -> str:
    return (f"[2026-09-28 10:00:{sec:02d}] LOCAL-STATS v=1 sess=aaaa1111 agent={agent8}"
            " model=qwen-local output_tokens=500 stop_reason=tool_use wall_s=2.00 clamped=0")


def _events(lines):
    return [ev for ev in (rs.parse_line(line) for line in lines) if ev]


def _served(tmp_path, lines):
    state = aw.arm(tmp_path / "w" / "2.2.watch.json", attempt_id="t22", agent_id=AGENT,
                   rung="local-medium", phase="cheap", router_log=None, now=0.0)
    return aw.verdict(state, None, _events(lines), CFG, 10.0)["served"]


# --- served.fallback_requests ----------------------------------------------------

def test_fallback_requests_counts_only_the_agents_own_fallback_posts(tmp_path):
    mine = AGENT[:8]
    lines = []
    for sec in (1, 3, 5):  # three local requests, each answered by LOCAL-STATS
        lines += [_post(sec, mine, "local"), _stats(sec + 1, mine)]
    lines += [_post(10, mine, "fallback"), _post(12, mine, "fallback")]
    lines += [_post(11, OTHER, "fallback"), _post(13, OTHER, "fallback"),
              _post(14, OTHER, "fallback")]  # another agent's bounces never count
    served = _served(tmp_path, lines)
    assert served["local_requests"] == 3
    assert served["fallback_requests"] == 2


def test_fallback_requests_present_and_zero_when_the_agent_has_none(tmp_path):
    mine = AGENT[:8]
    only_local = [_post(1, mine, "local"), _stats(2, mine), _post(3, OTHER, "fallback")]
    assert _served(tmp_path, only_local)["fallback_requests"] == 0
    assert _served(tmp_path, [])["fallback_requests"] == 0


def test_fallback_requests_count_without_any_local_stats(tmp_path):
    """Every request bounced: the slot never served, so local 0 beside fallback 2."""
    mine = AGENT[:8]
    served = _served(tmp_path, [_post(1, mine, "fallback"), _post(2, mine, "fallback")])
    assert (served["local_requests"], served["fallback_requests"]) == (0, 2)


# --- orphans: phase=None matches every phase --------------------------------------

@pytest.fixture
def ladder(tmp_path):
    """Two running orphans (phase "3" and "cheap"), each with a mid-turn transcript."""
    subagents = tmp_path / "projects" / "proj" / "sess" / "subagents"
    subagents.mkdir(parents=True)
    body = "\n".join(json.dumps(r) for r in CASES["mid_tool_call"]) + "\n"
    ldir = tmp_path / "ladder"
    for attempt, agent8, phase in (("p3", "c0000003", "3"), ("pc", "d0000004", "cheap")):
        (subagents / f"agent-{agent8}.jsonl").write_text(body, encoding="utf-8")
        aw.arm(ldir / f"{attempt}.watch.json", attempt_id=attempt, agent_id=agent8,
               rung="local-medium", phase=phase, router_log=None, now=0.0)
        aw.mark_orphan(ldir / f"{attempt}.watch.json", now=1.0)
    return {"dir": ldir, "config_dir": tmp_path, "log": tmp_path / "absent-router.log"}


def _running(out) -> dict:
    return {o["attempt_id"]: o["state"] for o in out["orphans"]}


def test_orphans_phase_none_reports_every_phase(ladder):
    out = aw.orphans(ladder["dir"], phase=None, config_dir=ladder["config_dir"],
                     router_log=ladder["log"])
    assert _running(out) == {"p3": "running", "pc": "running"}
    assert out["holds_gpu"] is True


def test_orphans_concrete_phase_still_filters(ladder):
    out = aw.orphans(ladder["dir"], phase="3", config_dir=ladder["config_dir"],
                     router_log=ladder["log"])
    assert _running(out) == {"p3": "running"}


def test_cli_orphans_phase_any_prints_the_phase_none_set(ladder):
    buf, real = io.StringIO(), sys.stdout
    sys.stdout = buf
    try:
        rc = aw.main(["orphans", "--dir", str(ladder["dir"]), "--phase", "any",
                      "--config-dir", str(ladder["config_dir"]),
                      "--router-log", str(ladder["log"])])
    finally:
        sys.stdout = real
    assert rc == 0
    direct = aw.orphans(ladder["dir"], phase=None, config_dir=ladder["config_dir"],
                        router_log=ladder["log"])
    assert json.loads(buf.getvalue()) == direct
    assert set(_running(direct)) == {"p3", "pc"}
