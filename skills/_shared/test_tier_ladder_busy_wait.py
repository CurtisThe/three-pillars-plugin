"""test_tier_ladder_busy_wait.py — the task ladder waits on a busy local rung.

design: one-cheap-engine (task 2.5)

Under ``busy_policy="wait"`` a ``local-busy`` unavailable keeps the rung (no attempt
spent) until ``strata_spawn.CEILING_S``, then halts. ``fallback`` is the old walk.
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
ROUTED = {"schema": "tp-local-route/v1", "state": "routed", "reason": "ok",
          "base_url": "http://127.0.0.1:3457", "checked_at": "2026-09-27T00:00:00Z"}


def _busy(policy, waited_since=None, now=1000.0, reason="local-busy"):
    rec = tier_ladder.start("2.5", "local-medium")
    return tier_ladder.next_step(rec, "unavailable", CFG, reason=reason, busy_policy=policy,
                                 waited_since=waited_since, now=now)


def test_wait_keeps_rung_no_attempt():
    action, rung, rec = _busy("wait", waited_since=900.0)
    assert (action, rung) == ("wait", "local-medium")
    assert rec["tier_path"] == ["local-medium"] and rec["final"] is None
    assert rec["attempts"].get("local-medium", 0) == 0


def test_wait_halts_at_ceiling():
    action, rung, rec = _busy("wait", waited_since=1000.0 - strata_spawn.CEILING_S)
    assert (action, rung) == ("halt", None)
    assert rec["final"] == "busy-timeout"


def test_fallback_unchanged():
    action, rung, _ = _busy("fallback", waited_since=0.0)
    assert (action, rung) == ("escalate", "sonnet-medium")


def test_cli_busy_policy_flag(tmp_path):
    rec, root = tmp_path / "R.json", tmp_path / "bare"
    root.mkdir()
    env = dict(os.environ)
    env.pop("ANTHROPIC_BASE_URL", None)

    def cli(*a):
        return subprocess.run([sys.executable, SCRIPT, *a], capture_output=True, text=True,
                              timeout=60, env=env)
    assert cli("start", "--task", "2.5", "--tier", "local", "--record", str(rec),
               "--route", json.dumps(ROUTED), "--root", str(root)).returncode == 0
    p = cli("next", "--record", str(rec), "--outcome", "unavailable", "--root", str(root),
            "--reason", "local-busy", "--busy-policy", "wait")
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["action"] == "wait" and out["rung"] == "local-medium"


def test_no_local_ladder_two_sonnet_failures_reach_opus():
    rec = tier_ladder.start("2.5", "sonnet-xhigh")
    action, rung, rec = tier_ladder.next_step(rec, "FAIL", CFG, reason="same red")
    assert (action, rung) == ("retry", "sonnet-xhigh")
    action, rung, rec = tier_ladder.next_step(rec, "FAIL", CFG, reason="same red")
    assert action == "escalate" and rung.startswith("opus-")
