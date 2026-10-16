"""finder_round mark-busy (local-role-routing 6.10)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "finder_round.py"


def _manifest(tmp_path):
    m = {"angles": [
        {"name": "a", "advisory": True, "model": "local"},
        {"name": "b", "advisory": True, "model": "local", "skipped": "out-of-scope"},
        {"name": "opus-check", "model": "opus"},
    ]}
    path = tmp_path / "angles.json"
    path.write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
    return path


def _run(tmp_path, angle):
    return subprocess.run([sys.executable, str(SCRIPT), "mark-busy", "--round-dir",
                           str(tmp_path), "--angle", angle],
                          capture_output=True, text=True, timeout=60)


def test_mark_busy_sets_only_that_entry_and_is_idempotent(tmp_path):
    path = _manifest(tmp_path)
    before = json.loads(path.read_text(encoding="utf-8"))
    assert _run(tmp_path, "a").returncode == 0
    after = json.loads(path.read_text(encoding="utf-8"))
    assert after["angles"][0]["served"] == "sonnet-busy"
    assert after["angles"][1:] == before["angles"][1:]
    once = path.read_bytes()
    assert _run(tmp_path, "a").returncode == 0
    assert path.read_bytes() == once


def test_mark_busy_refuses_unknown_check_and_out_of_scope(tmp_path):
    path = _manifest(tmp_path)
    raw = path.read_bytes()
    for angle in ("nope", "opus-check", "b"):
        assert _run(tmp_path, angle).returncode == 2
    assert path.read_bytes() == raw
