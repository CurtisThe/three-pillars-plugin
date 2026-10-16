"""test_tier_ladder_lease_wait.py — ``next --lease-wait-s`` reaches the verdict.

design: cheap-tier-local-routing (task 2.3)

The flag stores ``lease_wait_s`` (a float) on the verdict; without it the record
carries no ``lease_wait_s`` key at all (not a null).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = str(Path(__file__).resolve().parent / "tier_ladder.py")
ROUTED = {"schema": "tp-local-route/v1", "state": "routed", "reason": "ok",
          "base_url": "http://127.0.0.1:3457", "checked_at": "2026-09-27T00:00:00Z"}


def _cli(*args: str) -> int:
    env = dict(os.environ)
    env.pop("ANTHROPIC_BASE_URL", None)
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True,
                          timeout=60, env=env).returncode


def _step(tmp_path: Path, *extra: str) -> dict:
    rec, root = tmp_path / "R.json", tmp_path / "bare"
    root.mkdir(exist_ok=True)
    assert _cli("start", "--task", "2.3", "--tier", "local", "--record", str(rec),
                "--route", json.dumps(ROUTED), "--root", str(root)) == 0
    assert _cli("next", "--record", str(rec), "--outcome", "PASS", "--root", str(root),
                "--reason", "ok", *extra) == 0
    return json.loads(rec.read_text(encoding="utf-8"))


def test_flag_lands_on_the_verdict_as_a_float(tmp_path):
    rec = _step(tmp_path, "--lease-wait-s", "240")
    assert rec["verdicts"][-1]["lease_wait_s"] == 240.0
    assert isinstance(rec["verdicts"][-1]["lease_wait_s"], float)


def test_without_the_flag_there_is_no_key(tmp_path):
    rec = _step(tmp_path)
    assert "lease_wait_s" not in rec["verdicts"][-1]
    assert "lease_wait_s" not in json.dumps(rec)
