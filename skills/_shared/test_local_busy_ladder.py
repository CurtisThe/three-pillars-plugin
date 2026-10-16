"""test_local_busy_ladder.py — a held slot never runs a local rung as disguised Sonnet (Q1).

design: run-throughput (operator ruling Q1, PR #178 fix pass)

Behavior on the ladder transition and the telemetry record: `local-busy` is `unavailable`
(no local attempt spent, straight to the sonnet family); an attempt whose router stats
show zero local requests (fixture router log: every request of that agent went
`FALLBACK upstream`) is `served_by: fallback` with `local-fallback-served`, never local —
in the verdict, the telemetry record and the `[dispatch]` line.
"""
from __future__ import annotations

import json
from pathlib import Path

import attempt_watchdog as aw
import ladder_entry
import router_stats as rs
import tier_ladder

LOG = Path(__file__).resolve().parent / "fixtures" / "router_stats" / "fallback_served.log"
CFG = {"escalate": True, "max_retries": 2, "model": "qwen-local", "fallback_model": "sonnet"}


def _poll_from_fixture(tmp_path, agent_id: str) -> dict:
    """The watchdog's finished read of the fixture router log for one agent."""
    state = aw.arm(tmp_path / "w.json", attempt_id="t", agent_id=agent_id, rung="local-medium",
                   phase="1", router_log=None, now=0.0)
    events = [ev for ev in map(rs.parse_line, LOG.read_text(encoding="utf-8").splitlines()) if ev]
    return aw.verdict(state, None, events, {}, 10.0, finished=True)


def test_local_busy_is_unavailable_straight_to_sonnet_no_attempt_spent():
    rec = tier_ladder.start("1.1", "local-xhigh")
    action, rung, out = tier_ladder.next_step(rec, "unavailable", CFG, reason="local-busy")
    assert (action, rung) == ("escalate", "sonnet-xhigh")
    assert out["attempts"] == {"local-xhigh": 0, "sonnet-xhigh": 0}
    assert out["verdicts"][-1]["served_by"] is None  # nothing ran
    assert "local-busy" in ladder_entry.to_decision_entry(out)


def test_zero_local_requests_is_fallback_served_never_local(tmp_path):
    poll = _poll_from_fixture(tmp_path, "a0000011-worker")
    assert poll["served"]["local_requests"] == 0
    rec = tier_ladder.start("1.2", "local-medium")
    _a, _r, out = tier_ladder.next_step(rec, "PASS", CFG,
                                         evidence={"gen": poll["gen"], "served": poll["served"]})
    v = out["verdicts"][-1]
    assert v["served_by"] == "fallback" and rs.FALLBACK_SERVED in v["flags"]
    tele = ladder_entry.to_telemetry(out)["verdicts"][-1]
    assert tele["served_by"] == "fallback" and rs.FALLBACK_SERVED in tele["flags"]
    entry = ladder_entry.to_decision_entry(out)
    assert "served-by-fallback" in entry and "qwen-local" not in entry
    assert "flag: local-fallback-served" in entry


def test_local_requests_seen_is_served_local(tmp_path):
    poll = _poll_from_fixture(tmp_path, "b0000022-worker")
    assert poll["served"]["local_requests"] == 1
    rec = tier_ladder.start("1.3", "local-medium")
    _a, _r, out = tier_ladder.next_step(rec, "PASS", CFG, evidence={"served": poll["served"]})
    assert out["verdicts"][-1]["served_by"] == "local"
    assert rs.FALLBACK_SERVED not in out["verdicts"][-1]["flags"]


def test_served_by_is_the_one_derivation():
    assert rs.served_by("local", 3) == "local"
    assert rs.served_by("local", 0) == rs.served_by("local", None) == "fallback"
    assert (rs.served_by("sonnet", 0), rs.served_by("opus", None)) == ("sonnet", "opus")
    assert json.dumps(rs.served_by("inline", 1)) == "null"


# --- nothing spawned: an env-error is never served (PR #178 r2 test-quality) -----------

def test_rejected_spawn_is_not_served_by_fallback():
    """The r2 reproducer: the Agent tool rejected the variant, so nothing ran."""
    rec = tier_ladder.start("1.1", "local-medium")
    _a, _r, out = tier_ladder.next_step(
        rec, "env-error", CFG, reason="agent-unresolved: three-pillars:tp-task-worker-local-medium")
    v = out["verdicts"][-1]
    assert v["served_by"] is None
    assert rs.FALLBACK_SERVED not in v["flags"]
    entry = ladder_entry.to_decision_entry(out)
    assert "served-by-fallback" not in entry and "flag: local-fallback-served" not in entry


def test_env_error_without_spawn_evidence_is_not_served():
    """Any other pre-spawn env-error (e.g. `open` dirty-tree) records nothing served."""
    for rung in ("local-medium", "sonnet-medium"):
        rec = tier_ladder.start("1.4", rung)
        _a, _r, out = tier_ladder.next_step(rec, "env-error", CFG, reason="dirty-tree")
        assert out["verdicts"][-1]["served_by"] is None
        assert rs.FALLBACK_SERVED not in out["verdicts"][-1]["flags"]


def test_env_error_after_a_spawn_keeps_who_served(tmp_path):
    """A check/land exit 2 after a real attempt still says who served it."""
    poll = _poll_from_fixture(tmp_path, "b0000022-worker")
    rec = tier_ladder.start("1.5", "local-medium")
    _a, _r, out = tier_ladder.next_step(rec, "env-error", CFG, reason="land-conflict",
                                         evidence={"served": poll["served"]})
    assert out["verdicts"][-1]["served_by"] == "local"
    rec = tier_ladder.start("1.6", "sonnet-medium")
    _a, _r, out = tier_ladder.next_step(rec, "env-error", CFG, reason="land-conflict",
                                         evidence={"wall_s": 42.0})
    assert out["verdicts"][-1]["served_by"] == "sonnet"
