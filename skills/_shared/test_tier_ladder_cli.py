"""test_tier_ladder_cli.py — the JSON-record CLI equals the pure ladder functions.

design: local-implement-and-review (Behaviors 4, 6, 7)

Prose dispatchers carry the ladder record as a JSON file across turns:
``start`` writes it, ``next`` rewrites it and prints ``{action, tier, rung, agent, model}``,
``entry`` / ``telemetry`` render it. Config comes from ``local_implement_config.load``,
``DEFAULTS`` when the block is absent.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import tier_ladder
from local_implement_config import DEFAULTS
from agent_ref import resolve as _ref  # the spawn reference (this install's plugin name)

SCRIPT = str(Path(__file__).resolve().parent / "tier_ladder.py")

ROUTED = {"schema": "tp-local-route/v1", "state": "routed", "reason": "ok",
          "base_url": "http://127.0.0.1:3457", "checked_at": "2026-09-27T00:00:00Z"}


def cli(*args: str) -> tuple[int, str]:
    env = dict(os.environ)
    env.pop("ANTHROPIC_BASE_URL", None)
    proc = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True,
                          timeout=60, env=env)
    return proc.returncode, proc.stdout


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _unstamped(rec: dict) -> dict:
    """``rec`` without the CLI's clock stamps (H2), which the pure functions never add."""
    out = {k: v for k, v in rec.items() if k != "stepped_at"}
    out["verdicts"] = [{k: v for k, v in vd.items() if k not in ("started_at", "ended_at")}
                       for vd in rec.get("verdicts") or []]
    return out


def test_cli_round_trip(tmp_path):
    rec_path = tmp_path / "R.json"
    bare = tmp_path / "bare"
    bare.mkdir()
    rc, out = cli("start", "--task", "2.3", "--tier", "local", "--record", str(rec_path),
                  "--route", json.dumps(ROUTED), "--root", str(bare))
    assert rc == 0 and json.loads(out) == {
        "tier": "local", "rung": "local-medium", "agent": "tp-task-worker-local-medium", "agent_ref": _ref("tp-task-worker-local-medium"),
        "model": "haiku", "reason": "routed/ok", "plan_tier": "local", "display": "local"}
    assert _unstamped(_load(rec_path)) == {**tier_ladder.start("2.3", "local-medium"),
                                           "route": "routed/ok"}
    assert tier_ladder.start("2.3", "local") == tier_ladder.start("2.3", "local-medium")

    before = _load(rec_path)
    rc, out = cli("next", "--record", str(rec_path), "--outcome", "FAIL", "--root", str(bare),
                  "--reason", "red test")
    action, rung, want = tier_ladder.next_step(before, "FAIL", DEFAULTS, reason="red test")
    assert rc == 0 and json.loads(out) == {
        "action": action, "tier": "local", "rung": rung,
        "agent": "tp-task-worker-local-medium", "agent_ref": _ref("tp-task-worker-local-medium"), "model": "haiku"}
    assert (action, rung) == ("retry", "local-medium")
    assert _unstamped(_load(rec_path)) == _unstamped(want)

    cfg_root = tmp_path / "cfg"
    (cfg_root / ".three-pillars").mkdir(parents=True)
    block = {"enabled": True, "model": "qwen-coder", "max_retries": 1}
    (cfg_root / ".three-pillars" / "config.json").write_text(
        json.dumps({"local_implement": block}), encoding="utf-8")
    rc, out = cli("next", "--record", str(rec_path), "--outcome", "FAIL", "--root", str(cfg_root))
    assert json.loads(out) == {"action": "escalate", "tier": "local", "rung": "local-xhigh",
                               "agent": "tp-task-worker-local-xhigh", "agent_ref": _ref("tp-task-worker-local-xhigh"), "model": "qwen-coder"}
    rc, out = cli("next", "--record", str(rec_path), "--outcome", "PASS", "--root", str(cfg_root),
                  "--red-at-base", "meaningful")
    assert json.loads(out) == {"action": "done", "tier": None, "rung": None, "agent": None, "agent_ref": None,
                               "model": None}

    final = _load(rec_path)
    assert final["final"] == "done" and final["red_at_base"] == "meaningful"
    rc, out = cli("entry", "--record", str(rec_path))
    assert rc == 0 and out == tier_ladder.to_decision_entry(final)
    rc, out = cli("telemetry", "--record", str(rec_path))
    assert rc == 0 and json.loads(out) == tier_ladder.to_telemetry(final)

    rc, _out = cli("next", "--record", str(rec_path), "--outcome", "PASS", "--root", str(bare))
    assert rc == 2 and _load(rec_path) == final  # a final record is left untouched
