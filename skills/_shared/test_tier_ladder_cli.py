"""test_tier_ladder_cli.py — the JSON-record CLI equals the pure ladder functions.

design: local-implement-and-review (Behaviors 4, 6, 7)

Prose dispatchers carry the ladder record as a JSON file across turns:
``start`` writes it, ``next`` rewrites it and prints ``{action, tier, model}``,
``entry`` / ``telemetry`` render it. Config comes from ``local_implement_config.load``,
``DEFAULTS`` when the block is absent.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import tier_ladder
from local_implement_config import DEFAULTS

SCRIPT = str(Path(__file__).resolve().parent / "tier_ladder.py")


def cli(*args: str) -> tuple[int, str]:
    proc = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True,
                          timeout=60)
    return proc.returncode, proc.stdout


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_cli_round_trip(tmp_path):
    rec_path = tmp_path / "R.json"
    rc, out = cli("start", "--task", "2.3", "--tier", "local", "--record", str(rec_path))
    assert rc == 0 and json.loads(out) == _load(rec_path) == tier_ladder.start("2.3", "local")

    bare = tmp_path / "bare"
    bare.mkdir()
    before = _load(rec_path)
    rc, out = cli("next", "--record", str(rec_path), "--outcome", "FAIL", "--root", str(bare),
                  "--reason", "red test")
    action, tier, want = tier_ladder.next_step(before, "FAIL", DEFAULTS, reason="red test")
    assert rc == 0 and json.loads(out) == {"action": action, "tier": tier, "model": "haiku"}
    assert action == "retry" and _load(rec_path) == want

    cfg_root = tmp_path / "cfg"
    (cfg_root / ".three-pillars").mkdir(parents=True)
    block = {"enabled": True, "model": "qwen-coder", "max_retries": 1}
    (cfg_root / ".three-pillars" / "config.json").write_text(
        json.dumps({"local_implement": block}), encoding="utf-8")
    rc, out = cli("next", "--record", str(rec_path), "--outcome", "FAIL", "--root", str(cfg_root))
    assert json.loads(out) == {"action": "escalate", "tier": "sonnet", "model": "sonnet"}
    rc, out = cli("next", "--record", str(rec_path), "--outcome", "PASS", "--root", str(cfg_root),
                  "--red-at-base", "meaningful")
    assert json.loads(out) == {"action": "done", "tier": None, "model": None}

    final = _load(rec_path)
    assert final["final"] == "done" and final["red_at_base"] == "meaningful"
    rc, out = cli("entry", "--record", str(rec_path))
    assert rc == 0 and out == tier_ladder.to_decision_entry(final)
    rc, out = cli("telemetry", "--record", str(rec_path))
    assert rc == 0 and json.loads(out) == tier_ladder.to_telemetry(final)

    rc, _out = cli("next", "--record", str(rec_path), "--outcome", "PASS", "--root", str(bare))
    assert rc == 2 and _load(rec_path) == final  # a final record is left untouched
