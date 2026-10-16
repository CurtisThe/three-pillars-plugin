"""The certifier-at-most-once marker predicate + CLI (design: review-convergence 12.2)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cert_once  # noqa: E402

MODULE = Path(__file__).resolve().parent / "cert_once.py"
MARKER = "certify-once.json"


def test_should_run_true_on_fresh_dir(tmp_path):
    assert cert_once.should_run(tmp_path) is True


def test_should_run_false_after_mark(tmp_path):
    cert_once.mark(tmp_path, 1)
    assert cert_once.should_run(tmp_path) is False


def test_should_run_true_for_missing_dir(tmp_path):
    assert cert_once.should_run(tmp_path / "nope") is True


def test_mark_writes_marker_json(tmp_path):
    cert_once.mark(tmp_path, 3)
    marker = tmp_path / MARKER
    assert marker.exists()
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["slot"] == 8
    assert payload["attempt"] == 3
    assert isinstance(payload["at"], str) and payload["at"]


def test_mark_defaults_to_attempt_one(tmp_path):
    cert_once.mark(tmp_path)
    payload = json.loads((tmp_path / MARKER).read_text(encoding="utf-8"))
    assert payload["attempt"] == 1


def test_mark_is_idempotent_last_write_wins(tmp_path):
    cert_once.mark(tmp_path, 1)
    cert_once.mark(tmp_path, 2)
    payload = json.loads((tmp_path / MARKER).read_text(encoding="utf-8"))
    assert payload["attempt"] == 2
    assert cert_once.should_run(tmp_path) is False


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, str(MODULE), *args],
        capture_output=True,
        text=True,
        cwd=str(MODULE.parent),
    )


def test_cli_run_then_skip_sequence(tmp_path):
    first = _run_cli("should-run", "--design-dir", str(tmp_path))
    assert first.returncode == 0, first.stderr
    assert "run" in first.stdout

    marked = _run_cli("mark", "--design-dir", str(tmp_path))
    assert marked.returncode == 0, marked.stderr
    assert (tmp_path / MARKER).exists()

    second = _run_cli("should-run", "--design-dir", str(tmp_path))
    assert second.returncode == 1, second.stderr
    assert "skip" in second.stdout


def test_cli_mark_records_attempt(tmp_path):
    proc = _run_cli("mark", "--design-dir", str(tmp_path), "--attempt", "2")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads((tmp_path / MARKER).read_text(encoding="utf-8"))
    assert payload["attempt"] == 2


def test_cli_mark_missing_design_dir_exits_two(tmp_path):
    proc = _run_cli("mark", "--design-dir", str(tmp_path / "absent"))
    assert proc.returncode == 2
    assert proc.stderr.strip()
