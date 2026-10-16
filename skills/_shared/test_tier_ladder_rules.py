"""test_tier_ladder_rules.py — the rung-aware total table of ``next_step``.

design: run-throughput (detailed-design.md §tier_ladder, plan-notes §Legacy ladder records)

One case per table row, the replay fixture (a plan-gap ``unlisted file`` escalates after one
attempt, not three), varied failures that never trip ``stuck``, each ``unavailable`` case, the
rung-aware route floor and the legacy-family record rule.
"""
from __future__ import annotations

import pytest

import failure_class
import tier_ladder
from local_implement_config import DEFAULTS

CFG = {**DEFAULTS, "max_retries": 1}  # N = 2 attempts per cheap rung
NO_ESC = {**CFG, "escalate": False}
ROUTED = "routed/ok"
UNROUTED = "unrouted/no-base-url"


def _rec(rung: str, attempts: int = 0, route: str = ROUTED) -> dict:
    return {"task_id": "9.9", "tier_path": [rung], "attempts": {rung: attempts},
            "escalated": False, "final": None, "verdicts": [], "tokens": None, "route": route}


def _step(rec, outcome, cfg=CFG, reason="", **evidence):
    return tier_ladder.next_step(rec, outcome, cfg, reason=reason, evidence=evidence or None)


@pytest.mark.parametrize("rung", ["local-medium", "local-xhigh", "sonnet-medium",
                                  "sonnet-xhigh", "opus-medium", "opus-xhigh"])
def test_pass_and_env_error_rows(rung):
    for outcome, final in (("PASS", "done"), ("PASS-unverified", "done-unverified")):
        action, nxt, out = _step(_rec(rung), outcome)
        assert (action, nxt, out["final"], out["attempts"][rung]) == ("done", None, final, 1)
    action, nxt, out = _step(_rec(rung, 1), "env-error")
    assert (action, nxt, out["final"], out["attempts"]) == ("halt", None, "env-error", {rung: 1})


@pytest.mark.parametrize("rung,up", [
    ("local-medium", "sonnet-medium"), ("local-xhigh", "sonnet-xhigh"),
    ("sonnet-medium", "opus-medium"), ("sonnet-xhigh", "opus-xhigh")])
def test_unavailable_same_effort_next_family(rung, up):
    action, nxt, out = _step(_rec(rung), "unavailable", reason="orphan-holds-gpu")
    assert (action, nxt, out["attempts"]) == ("escalate", up, {rung: 0, up: 0})
    assert out["verdicts"][-1]["class"] == "unavailable" and out["escalated"] is True
    action, nxt, out = _step(_rec(rung), "unavailable", NO_ESC)
    assert (action, nxt, out["final"], out["attempts"][rung]) == ("blocked", None, "blocked", 0)


@pytest.mark.parametrize("rung", ["opus-medium", "opus-xhigh"])
def test_opus_unavailable_blocks(rung):
    """Q4: a spawned opus rung can be unavailable; there is no family above it."""
    action, nxt, out = _step(_rec(rung), "unavailable")
    assert (action, nxt, out["final"], out["attempts"][rung]) == ("blocked", None, "blocked", 0)


def test_deterministic_jumps_without_same_rung_retry():
    reason = "unlisted file: skills/_shared/hot_patch.py"
    action, nxt, out = _step(_rec("local-medium"), "FAIL", reason=reason)
    assert (action, nxt) == ("escalate", "opus-medium")
    assert out["attempts"] == {"local-medium": 1, "opus-medium": 0}
    v = out["verdicts"][-1]
    assert (v["class"], v["stuck"]) == ("deterministic:unlisted-file", "deterministic")
    assert _step(_rec("sonnet-xhigh"), "FAIL", reason=reason)[:2] == ("escalate", "opus-xhigh")
    assert _step(_rec("opus-medium"), "FAIL", reason=reason)[:2] == ("escalate", "opus-xhigh")
    action, _n, out = _step(_rec("opus-xhigh"), "FAIL", reason=reason)
    assert (action, out["final"]) == ("blocked", "blocked")
    action, _n, out = _step(_rec("local-medium"), "FAIL", NO_ESC, reason=reason)
    assert (action, out["final"], out["verdicts"][-1]["stuck"]) == (
        "blocked", "blocked", "deterministic")


def test_replay_plan_gap_escalates_after_one_attempt():
    """Seed Part C's 4.6/4.7 replay: three local tries on a plan gap become one."""
    rec = tier_ladder.start("4.6", "local")
    rec["route"] = ROUTED
    action, nxt, out = tier_ladder.next_step(
        rec, "FAIL", {**DEFAULTS, "max_retries": 2},
        reason="unlisted file: skills/_shared/hot_patch.py")
    assert (action, nxt) == ("escalate", "opus-medium")
    assert out["attempts"]["local-medium"] == 1
    assert out["tier_path"] == ["local-medium", "opus-medium"]


def test_no_oracle_escalates_at_once_without_attempt():
    reason = "no oracle (a cheap rung needs a runnable Test)"
    action, nxt, out = _step(_rec("local-medium"), "FAIL", reason=reason)
    assert (action, nxt, out["attempts"]) == (
        "escalate", "opus-medium", {"local-medium": 0, "opus-medium": 0})
    action, _n, out = _step(_rec("opus-xhigh"), "FAIL", reason=reason)
    assert (action, out["attempts"]["opus-xhigh"]) == ("blocked", 1)


def test_repeated_fingerprint_on_this_rung_escalates():
    cfg = {**CFG, "max_retries": 5}
    rec = _rec("local-medium")
    action, _n, rec = _step(rec, "FAIL", cfg, reason="red test", failing_tests=["t.py::a"])
    assert action == "retry" and rec["verdicts"][-1]["stuck"] is None
    action, nxt, rec = _step(rec, "FAIL", cfg, reason="red test", failing_tests=["t.py::a"])
    assert (action, nxt) == ("escalate", "local-xhigh")
    v = rec["verdicts"][-1]
    assert v["stuck"] == "repeated-failure"
    assert v["fingerprint"] == rec["verdicts"][0]["fingerprint"]


def test_varied_failures_never_stuck():
    """Same single-file target failing different nodes: different fingerprints, no stuck."""
    cfg = {**CFG, "max_retries": 5}
    rec = _rec("local-medium")
    for node in ("a", "b", "c", "d"):
        action, nxt, rec = _step(rec, "FAIL", cfg, reason="red test",
                                 failing_tests=[f"skills/t.py::{node}"])
        assert (action, nxt) == ("retry", "local-medium")
    assert all(v["stuck"] is None for v in rec["verdicts"])
    assert len({v["fingerprint"] for v in rec["verdicts"]}) == 4


def test_same_failure_on_two_rungs_one_fingerprint_no_stuck():
    cfg = {**CFG, "max_retries": 0}
    rec = _rec("local-medium")
    _a, nxt, rec = _step(rec, "FAIL", cfg, reason="red test", failing_tests=["t.py::a"])
    assert nxt == "local-xhigh"
    action, nxt, rec = _step(rec, "FAIL", cfg, reason="red test", failing_tests=["t.py::a"])
    assert (action, nxt) == ("escalate", "sonnet-xhigh")
    fps = [v["fingerprint"] for v in rec["verdicts"]]
    assert fps[0] == fps[1] == failure_class.fingerprint("FAIL", "red test", ["t.py::a"])
    assert [v["stuck"] for v in rec["verdicts"]] == [None, None]


def test_cheap_quality_retry_then_quality_next():
    for rung, up in (("local-medium", "local-xhigh"), ("local-xhigh", "sonnet-xhigh"),
                     ("sonnet-medium", "sonnet-xhigh"), ("sonnet-xhigh", "opus-xhigh")):
        assert _step(_rec(rung), "FAIL", reason="red test")[:2] == ("retry", rung)
        action, nxt, out = _step(_rec(rung, 1), "FAIL", reason="red test")
        assert (action, nxt, out["attempts"]) == ("escalate", up, {rung: 2, up: 0})
        action, _n, out = _step(_rec(rung, 1), "FAIL", NO_ESC, reason="red test")
        assert (action, out["final"]) == ("blocked", "blocked")


def test_opus_rungs_on_quality_fail():
    action, nxt, out = _step(_rec("opus-medium"), "FAIL", reason="red test")
    assert (action, nxt, out["attempts"]) == (
        "escalate", "opus-xhigh", {"opus-medium": 1, "opus-xhigh": 0})
    action, _n, out = _step(_rec("opus-xhigh"), "FAIL", reason="red test")
    assert (action, out["final"], out["attempts"]["opus-xhigh"]) == ("blocked", "blocked", 1)
    action, _n, out = _step(_rec("opus-medium"), "FAIL", NO_ESC, reason="red test")
    assert (action, out["final"]) == ("blocked", "blocked")


def test_verdict_keys():
    _a, _n, out = _step(_rec("local-medium"), "FAIL", reason="red test",
                        failing_tests=["t.py::a"], gen={"max": 9}, served={"turns": 3},
                        flags=["identical-calls 5x Bash"], tokens={"output": 7}, wall_s=12.5)
    v = out["verdicts"][-1]
    assert {k: v[k] for k in ("tier", "rung", "outcome", "reason", "class")} == {
        "tier": "local-medium", "rung": "local-medium", "outcome": "FAIL", "reason": "red test",
        "class": "quality"}
    # Q1: served stats with no local request → served by the router's fallback, flagged.
    assert (v["flags"], v["tokens"], v["wall_s"]) == (
        ["identical-calls 5x Bash", "local-fallback-served"], {"output": 7}, 12.5)
    assert (v["gen"], v["served"], v["served_by"]) == ({"max": 9}, {"turns": 3}, "fallback")
    _a, _n, out = _step(_rec("sonnet-xhigh"), "FAIL", reason="red test", gen={"max": 9})
    v = out["verdicts"][-1]
    assert "gen" not in v and "served" not in v
    assert (v["flags"], v["tokens"], v["wall_s"], v["stuck"]) == ([], None, None, None)
    assert v["served_by"] == "sonnet"


def test_route_floor_is_rung_aware():
    assert tier_ladder.route_floor("local-xhigh", UNROUTED) == ("sonnet-xhigh", True)
    assert tier_ladder.route_floor("local-xhigh", ROUTED) == ("local-xhigh", False)
    assert tier_ladder.route_floor("local-medium", "missing-route") == ("sonnet-medium", True)
    assert tier_ladder.route_floor("local", UNROUTED) == ("sonnet", True)
    assert tier_ladder.route_floor("sonnet-medium", UNROUTED) == ("sonnet-medium", False)
    assert tier_ladder.route_floor("localish", UNROUTED) == ("localish", False)


def test_legacy_family_record_normalizes_on_read():
    for family, rung in (("local", "local-medium"), ("sonnet", "sonnet-xhigh"),
                         ("opus", "opus-xhigh")):
        rec = {**tier_ladder.start("1.1", family), "route": ROUTED}
        _a, _n, out = _step(rec, "PASS")
        assert (out["tier_path"], out["attempts"]) == ([rung], {rung: 1})
    rec = {**tier_ladder.start("1.1", "local"), "route": ROUTED}
    assert _step(rec, "FAIL", reason="red test")[:2] == ("retry", "local-medium")
    rec["attempts"]["local"] = 1
    action, nxt, out = _step(rec, "FAIL", reason="red test")
    assert (action, nxt, out["tier_path"]) == (
        "escalate", "local-xhigh", ["local-medium", "local-xhigh"])


def test_next_floors_its_target_by_the_record_route():
    """A hand-built local record with no routed label never gets a local rung printed."""
    rec = {**tier_ladder.start("1.1", "local"), "route": UNROUTED}
    rec["attempts"]["local"] = 1
    action, nxt, out = _step(rec, "FAIL", reason="red test")
    assert (action, nxt) == ("escalate", "sonnet-xhigh")
    assert out["tier_path"] == ["local-medium", "sonnet-xhigh"]
    assert out["attempts"]["sonnet-xhigh"] == 0 and "local-xhigh" not in out["attempts"]
    assert out["floored_from"] == "local-xhigh"
    missing = {**tier_ladder.start("1.1", "local"), "route": "missing-route"}
    assert _step(missing, "FAIL", reason="red test")[:2] == ("escalate", "sonnet-medium")
    # The pure function floors only by a recorded route; the CLI records `missing-route`
    # on a pre-hybrid record first (test_tier_ladder_route_cli.py).
    assert _step(tier_ladder.start("1.1", "local"), "FAIL")[:2] == ("retry", "local-medium")
