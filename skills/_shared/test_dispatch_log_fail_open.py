"""dispatch_log.py record's "always exits 0" contract (run-throughput, PR #178 round 4).

design: run-throughput (detailed-design-part-a.md §Telemetry — dispatch_log.py)

Real CLI runs: a write that cannot land (a design dir that does not exist) is one stderr
note and exit 0 with the record still printed, never a traceback and exit 1.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

CLI = Path(__file__).resolve().parent / "dispatch_log.py"


def _record(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CLI), "record", "--role", "pr",
                           "--inline", "--reason", "slot 10", "--outcome", "ok", *args],
                          capture_output=True, text=True, timeout=60)


def test_missing_design_dir_exits_0_with_a_stderr_note(tmp_path):
    gone = tmp_path / "tp-designs" / "gone"
    proc = _record("--design-dir", str(gone), "--decisions", str(gone / "decisions.md"),
                   "--root", str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    assert "Traceback" not in proc.stderr
    assert "ndjson row not written" in proc.stderr
    assert "decisions.md line not written" in proc.stderr
    assert json.loads(proc.stdout)["outcome"] == "ok"  # the record is still printed
    assert not gone.exists()  # fail-open never invents the directory


def test_present_design_dir_still_writes_with_no_note(tmp_path):
    proc = _record("--design-dir", str(tmp_path), "--root", str(tmp_path))
    assert proc.returncode == 0 and proc.stderr == ""
    (row,) = (tmp_path / "dispatch-telemetry.ndjson").read_text(encoding="utf-8").splitlines()
    assert json.loads(row)["role"] == "pr"
