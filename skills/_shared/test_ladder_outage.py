"""test_ladder_outage.py — a zero-request clock-out is a backend-outage, not a runaway.

design: ladder-diagnose-and-size-pins (task 1.6, Behaviors B4, B6)

A local attempt that ends at its clock with router evidence of zero requests never ran: the
backend is down. The ladder takes the run's busy policy at once (fallback: the Sonnet rung of
the same effort; wait: stay on the rung, halting at the busy ceiling). With requests logged, or
with no evidence, it is still a ``runaway``. Pure ladder calls plus the CLI (fragility: no
timing, no network; the router evidence is a file).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import local_implement_config
import strata_spawn
import tier_ladder

CFG = {**local_implement_config.DEFAULTS, "escalate": True, "max_retries": 2}
SCRIPT = str(Path(__file__).resolve().parent / "tier_ladder.py")
CLOCK = "runaway: wall-clock 1214s ≥ 1200s"
ZERO = {"local_requests": 0, "fallback_requests": 0, "turns": 3}
BUSY80 = {"local_requests": 80, "fallback_requests": 0, "turns": 80}
ROUTED = {"schema": "tp-local-route/v1", "state": "routed", "reason": "ok",
          "base_url": "http://127.0.0.1:3457", "checked_at": "2026-10-24T00:00:00Z"}
DOWN = dict(ROUTED, state="router-down", reason="upstream-down")
OUTAGE = "backend-outage"
LINE = "outage: backend-outage probe=router-down/upstream-down"


def _run(rung, served, *, policy="fallback", reason=CLOCK, waited_since=None, now=1000.0):
    rec = tier_ladder.start("1.6", rung)
    ev = {"served": served} if served is not None else None
    return tier_ladder.next_step(rec, "FAIL", CFG, reason=reason, evidence=ev,
                                 busy_policy=policy, waited_since=waited_since, now=now)


def test_reclass_needs_zero_requests_of_both_kinds():
    import ladder_outage  # lazy: the other tests fail on the class, not on the import
    assert ladder_outage.OUTAGE == OUTAGE
    assert ladder_outage.reclass("runaway", CLOCK, {"served": ZERO}) == OUTAGE
    assert ladder_outage.reclass("runaway", CLOCK, {"served": BUSY80}) == "runaway"
    assert ladder_outage.reclass("runaway", CLOCK, {}) == "runaway"
    served = {"local_requests": 0, "fallback_requests": 2}
    assert ladder_outage.reclass("runaway", CLOCK, {"served": served}) == "runaway"
    assert ladder_outage.reclass("quality", "boom", {"served": ZERO}) == "quality"


def test_fallback_escalates_straight_to_same_effort_sonnet():
    for effort in ("medium", "xhigh"):
        action, rung, rec = _run(f"local-{effort}", ZERO)
        assert (action, rung) == ("escalate", f"sonnet-{effort}")
        assert rec["verdicts"][0]["class"] == OUTAGE
        assert rec["tier_path"] == [f"local-{effort}", f"sonnet-{effort}"]


def test_wait_stays_on_the_rung_and_halts_at_the_busy_ceiling():
    action, rung, rec = _run("local-medium", ZERO, policy="wait", waited_since=900.0)
    assert (action, rung) == ("wait", "local-medium")
    assert rec["tier_path"] == ["local-medium"] and rec["final"] is None
    stale = 1000.0 - strata_spawn.CEILING_S
    action, rung, rec = _run("local-medium", ZERO, policy="wait", waited_since=stale)
    assert (action, rung) == ("halt", None) and rec["final"] == "busy-timeout"


def test_requests_or_no_evidence_is_still_a_runaway():
    for served in (BUSY80, None):
        action, rung, rec = _run("local-medium", served)
        assert (action, rung) == ("escalate", "local-xhigh")
        assert rec["verdicts"][0]["class"] == "runaway"
        assert rec["verdicts"][0]["stuck"] == "runaway"


def test_a_claude_rung_is_never_an_outage():
    action, rung, rec = _run("sonnet-medium", ZERO)
    assert rec["verdicts"][0]["class"] == "runaway"
    assert (action, rung) == ("retry", "sonnet-medium")  # today's quality retry, unchanged


def test_upstream_down_unavailable_waits_under_wait_only():
    rec = tier_ladder.start("1.6", "local-medium")
    action, rung, _ = tier_ladder.next_step(rec, "unavailable", CFG, reason="upstream-down",
                                            busy_policy="wait", waited_since=900.0, now=1000.0)
    assert (action, rung) == ("wait", "local-medium")
    action, rung, _ = tier_ladder.next_step(rec, "unavailable", CFG, reason="upstream-down",
                                            busy_policy="fallback")
    assert (action, rung) == ("escalate", "sonnet-medium")


def _cli(*a):
    env = dict(os.environ)
    env.pop("ANTHROPIC_BASE_URL", None)
    return subprocess.run([sys.executable, SCRIPT, *a], capture_output=True, text=True,
                          timeout=60, env=env)


def _files(tmp_path, served, probe):
    root = tmp_path / "bare"
    root.mkdir()
    watch, key = tmp_path / "W.json", tmp_path / "K.json"
    watch.write_text(json.dumps({"served": served}), encoding="utf-8")
    key.write_text(json.dumps(probe), encoding="utf-8")
    rec = tmp_path / "R.json"
    start = _cli("start", "--task", "1.6", "--tier", "local", "--record", str(rec),
                 "--route", json.dumps(ROUTED), "--root", str(root))
    assert start.returncode == 0, start.stderr
    return rec, root, watch, key


def test_cli_probe_json_rides_the_outage_verdict_entry_and_telemetry(tmp_path):
    rec, root, watch, key = _files(tmp_path, ZERO, DOWN)
    p = _cli("next", "--record", str(rec), "--outcome", "FAIL", "--reason", CLOCK,
             "--root", str(root), "--watch-json", str(watch), "--probe-json", str(key))
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert (out["action"], out["rung"]) == ("escalate", "sonnet-medium")
    verdict = json.loads(rec.read_text(encoding="utf-8"))["verdicts"][0]
    assert verdict["class"] == OUTAGE
    assert verdict["probe"] == "router-down/upstream-down"
    entry = _cli("entry", "--record", str(rec)).stdout
    assert entry.splitlines().count(LINE) == 1
    tele = _cli("telemetry", "--record", str(rec)).stdout
    assert tele.count(LINE) == 1
    assert json.loads(tele)["outage"] == LINE


def test_cli_without_a_probe_or_an_outage_the_entry_has_no_outage_line(tmp_path):
    rec, root, watch, key = _files(tmp_path, BUSY80, ROUTED)
    p = _cli("next", "--record", str(rec), "--outcome", "FAIL", "--reason", CLOCK,
             "--root", str(root), "--watch-json", str(watch), "--probe-json", str(key))
    assert p.returncode == 0, p.stderr
    assert "outage:" not in _cli("entry", "--record", str(rec)).stdout
    tele = json.loads(_cli("telemetry", "--record", str(rec)).stdout)
    assert "outage" not in tele
