"""test_tier_ladder.py — the pure retry/escalation table, `[tier]` entry and telemetry.

design: local-implement-and-review (Behaviors 4, 6, 7)
"""
from __future__ import annotations

import copy

import pytest

import tier_ladder
from local_implement_config import DEFAULTS

CFG = {**DEFAULTS, "max_retries": 1}  # N = 2 attempts per cheap rung


def _at(tier: str, attempts: int = 0) -> dict:
    rec = tier_ladder.start("2.3", tier)
    rec["attempts"][tier] = attempts
    return rec


def _step(rec, outcome, cfg=CFG):
    action, tier, out = tier_ladder.next_step(rec, outcome, cfg)
    return action, tier, out


def test_total_table():
    for tier in tier_ladder.LADDER:
        for outcome, final in (("PASS", "done"), ("PASS-unverified", "done-unverified")):
            action, nxt, out = _step(_at(tier), outcome)
            assert (action, nxt, out["final"], out["attempts"][tier]) == ("done", None, final, 1)
    for tier, up in (("local", "sonnet"), ("sonnet", "opus")):
        action, nxt, out = _step(_at(tier), "FAIL")
        assert (action, nxt, out["attempts"][tier], out["final"]) == ("retry", tier, 1, None)
        action, nxt, out = _step(_at(tier, 1), "FAIL")
        assert (action, nxt, out["escalated"]) == ("escalate", up, True)
        assert out["tier_path"] == [tier, up] and out["attempts"] == {tier: 2, up: 0}
        no_esc = {**CFG, "escalate": False}
        action, nxt, out = _step(_at(tier, 1), "FAIL", no_esc)
        assert (action, nxt, out["final"]) == ("blocked", None, "blocked")
        action, nxt, out = _step(_at(tier), "unavailable")
        assert (action, nxt, out["attempts"]) == ("escalate", up, {tier: 0, up: 0})
        action, nxt, out = _step(_at(tier), "unavailable", no_esc)
        assert (action, nxt, out["final"], out["attempts"][tier]) == ("blocked", None, "blocked", 0)
    action, nxt, out = _step(_at("opus"), "FAIL")
    assert (action, nxt, out["final"], out["attempts"]["opus"]) == ("blocked", None, "blocked", 1)
    with pytest.raises(ValueError):
        _step(_at("opus"), "unavailable")
    with pytest.raises(ValueError):
        _step(_at("local"), "MAYBE")
    zero = {**CFG, "max_retries": 0}
    assert _step(_at("local"), "FAIL", zero)[:2] == ("escalate", "sonnet")


def test_no_oracle_escalates_at_once_without_attempt():
    """impl-audit-2 #7: a cheap rung's FAIL `no oracle` is deterministic, so no retry is
    spent on it: it escalates (or blocks) at once, like `unavailable`, 0 attempts counted.
    The verdict keeps FAIL and the reason; opus FAIL stays blocked (one inline try)."""
    import task_verify

    reason = "no oracle (a cheap rung needs a runnable Test)"
    assert reason.startswith(tier_ladder.NO_ORACLE)
    assert f'_Fail("{reason}")' in open(task_verify.__file__, encoding="utf-8").read()
    no_esc = {**CFG, "escalate": False}
    for tier, up in (("local", "sonnet"), ("sonnet", "opus")):
        action, nxt, out = tier_ladder.next_step(_at(tier), "FAIL", CFG, reason=reason)
        assert (action, nxt, out["attempts"]) == ("escalate", up, {tier: 0, up: 0})
        assert out["verdicts"] == [{"tier": tier, "outcome": "FAIL", "reason": reason}]
        action, nxt, out = tier_ladder.next_step(_at(tier), "FAIL", no_esc, reason=reason)
        assert (action, nxt, out["final"], out["attempts"][tier]) == ("blocked", None, "blocked", 0)
    action, _nxt, out = tier_ladder.next_step(_at("opus"), "FAIL", CFG, reason=reason)
    assert (action, out["final"], out["attempts"]["opus"]) == ("blocked", "blocked", 1)
    # Any other FAIL reason still retries on the same rung.
    assert tier_ladder.next_step(_at("local"), "FAIL", CFG, reason="red test")[:2] == (
        "retry", "local")


def test_env_error_halts_without_attempt():
    for tier in tier_ladder.LADDER:
        rec = _at(tier, 1)
        action, nxt, out = _step(rec, "env-error")
        assert (action, nxt, out["final"]) == ("halt", None, "env-error")
        assert out["attempts"] == {tier: 1} and out["tier_path"] == [tier]
    with pytest.raises(ValueError):  # a final record takes no further outcome
        _step(out, "PASS")


def test_next_step_is_pure():
    rec = tier_ladder.start("2.3", "local")
    before = copy.deepcopy(rec)
    _a, _t, out = tier_ladder.next_step(rec, "FAIL", CFG, reason="red test")
    assert rec == before and out is not rec
    assert out["verdicts"] == [{"tier": "local", "outcome": "FAIL", "reason": "red test"}]
    _a, _t, out2 = tier_ladder.next_step(out, "PASS", CFG, red_at_base="meaningful")
    assert out["final"] is None and len(out["verdicts"]) == 1
    assert (out2["final"], out2["red_at_base"]) == ("done", "meaningful")


def test_model_for_maps_config():
    cfg = {**DEFAULTS, "model": "qwen-coder", "fallback_model": "sonnet"}
    assert tier_ladder.model_for("local", cfg) == "qwen-coder"
    assert tier_ladder.model_for("sonnet", cfg) == "sonnet"
    assert tier_ladder.model_for("opus", cfg) is None
    assert tier_ladder.model_for("local", {**cfg, "model": "haiku"}) == "haiku"
    assert not hasattr(tier_ladder, "LOCAL_MODEL")


def _run(tier: str, *steps) -> dict:
    rec = tier_ladder.start("2.3", tier)
    for outcome, kw in steps:
        _a, _t, rec = tier_ladder.next_step(rec, outcome, CFG, **kw)
    return rec


def test_decision_entry_format():
    rec = _run("local", ("FAIL", {"reason": "red test"}), ("FAIL", {"reason": "2 commits"}),
               ("PASS", {"red_at_base": "meaningful"}))
    rec["tokens"] = 4321
    text = tier_ladder.to_decision_entry(rec)
    lines = text.splitlines()
    assert lines[0] == "### [tier] 2.3 — done"
    assert "**Tier path**: local → sonnet" in text
    assert "**Attempts**: local: 2 attempts, sonnet: 1 attempt" in text
    assert "local FAIL (red test)" in text and "local FAIL (2 commits)" in text
    assert "sonnet PASS" in text
    assert "**Red-at-base**: meaningful" in text and "**Tokens**: 4321" in text

    unverified = tier_ladder.to_decision_entry(_run("opus", ("PASS-unverified", {})))
    assert unverified.startswith("### [tier] 2.3 — done-unverified")
    assert "**Tokens**" not in unverified and "**Red-at-base**: n/a" in unverified
    env = tier_ladder.to_decision_entry(_run("sonnet", ("env-error", {"reason": "dispatcher moved"})))
    assert env.startswith("### [tier] 2.3 — env-error") and "dispatcher moved" in env
    skipped = tier_ladder.to_decision_entry(_run("local", ("unavailable", {}), ("PASS", {})))
    assert "**Attempts**: local: 0 attempts, sonnet: 1 attempt" in skipped
    assert "local unavailable" in skipped


def test_telemetry_record():
    rec = _run("local", ("unavailable", {}), ("FAIL", {"reason": "red test"}),
               ("PASS-unverified", {}))
    tel = tier_ladder.to_telemetry(rec)
    assert (tel["task_id"], tel["final"]) == ("2.3", "done-unverified")
    assert tel["tier_path"] == ["local", "sonnet"] and tel["escalated"] is True
    assert tel["attempts"] == {"local": 0, "sonnet": 2}
    assert tel["outcomes"] == ["unavailable", "FAIL", "PASS-unverified"]
    assert tel["tokens"] is None and tel["red_at_base"] is None
    tel["attempts"]["local"] = 9
    assert rec["attempts"]["local"] == 0  # a copy, not a view


def test_entry_from_telemetry_on_stdin():
    """impl-audit-1 #8: the orchestrator renders the one full-design `[tier]` entry from a
    `telemetry.task_tiers[]` item, keeping the lines /tp-phase-review step 2b reads."""
    import json
    import subprocess
    import sys
    from pathlib import Path

    rec = _run("local", ("FAIL", {"reason": "red test"}), ("PASS", {"red_at_base": "meaningful"}))
    tel = tier_ladder.to_telemetry(rec)
    script = str(Path(tier_ladder.__file__).resolve())
    proc = subprocess.run([sys.executable, script, "entry", "--record", "-"],
                          input=json.dumps(tel), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("### [tier] 2.3 — done\n")
    for line in ("**Tier path**: local", "**Attempts**: local: 2 attempts",
                 "**Verdicts**: local FAIL (red test); local PASS", "**Red-at-base**: meaningful"):
        assert line in proc.stdout, line
    bad = subprocess.run([sys.executable, script, "next", "--record", "-", "--outcome", "PASS"],
                         input="{}", capture_output=True, text=True)
    assert bad.returncode == 2 and "read-only" in bad.stderr


def test_telemetry_carries_rung_labelled_verdicts():
    """impl-audit-2 #5: `task_tiers[]` items keep `{tier, outcome, reason}` (reason clipped),
    so the orchestrator's entry names the rungs and reasons; an outcomes-only item still renders."""
    rec = _run("local", ("FAIL", {"reason": "red test " + "x" * 500}), ("PASS", {}))
    tel = tier_ladder.to_telemetry(rec)
    assert [(v["tier"], v["outcome"]) for v in tel["verdicts"]] == [
        ("local", "FAIL"), ("local", "PASS")]
    reason = tel["verdicts"][0]["reason"]
    assert reason.startswith("red test") and len(reason) == 200
    tel["verdicts"][0]["reason"] = "mutated"
    assert rec["verdicts"][0]["reason"].startswith("red test")  # a copy, never a view
    legacy = {k: v for k, v in tel.items() if k != "verdicts"}
    assert "**Verdicts**: FAIL; PASS" in tier_ladder.to_decision_entry(legacy)
