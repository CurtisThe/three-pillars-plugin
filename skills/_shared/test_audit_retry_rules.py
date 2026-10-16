"""The audit-retry lows predicate + CLI (design: run-throughput 5.3)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_retry_rules  # noqa: E402

MODULE = Path(__file__).resolve().parent / "audit_retry_rules.py"

CASES = [
    (
        "low-confidence critical is not lows",
        [{"confidence": "low", "severity": "critical", "category": "logic"}],
        False,
    ),
    (
        "all minor is lows",
        [
            {"confidence": "high", "severity": "minor", "category": "logic"},
            {"confidence": "low", "severity": "minor", "category": "style"},
        ],
        True,
    ),
    (
        "missing severity fails safe",
        [{"confidence": "high", "category": "logic"}],
        False,
    ),
    (
        "map-check-only is lows",
        [{"confidence": "high", "severity": "major", "category": "map-check"}],
        True,
    ),
    (
        "empty list is vacuously lows",
        [],
        True,
    ),
    (
        "one non-minor beside map-checks is not lows",
        [
            {"confidence": "high", "severity": "major", "category": "map-check"},
            {"confidence": "high", "severity": "major", "category": "logic"},
        ],
        False,
    ),
]


@pytest.mark.parametrize(("label", "findings", "expected"), CASES, ids=[c[0] for c in CASES])
def test_lows_only_table(label, findings, expected):
    assert audit_retry_rules.lows_only(findings) is expected


def _run_cli(payload_or_path):
    args = [sys.executable, str(MODULE), "lows-only", "--findings", str(payload_or_path)]
    return subprocess.run(args, capture_output=True, text=True, cwd=str(MODULE.parent))


def _write(tmp_path: Path, payload) -> Path:
    f = tmp_path / "findings.json"
    f.write_text(json.dumps(payload), encoding="utf-8")
    return f


def test_cli_exits_zero_when_lows(tmp_path):
    f = _write(tmp_path, [{"confidence": "low", "severity": "minor", "category": "style"}])
    proc = _run_cli(f)
    assert proc.returncode == 0, proc.stderr
    assert "yes" in proc.stdout


def test_cli_accepts_object_form(tmp_path):
    f = _write(tmp_path, {"findings": [{"severity": "minor", "category": "logic"}]})
    proc = _run_cli(f)
    assert proc.returncode == 0, proc.stderr


def test_cli_exits_one_when_not_lows(tmp_path):
    f = _write(tmp_path, {"findings": [{"severity": "major", "category": "logic"}]})
    proc = _run_cli(f)
    assert proc.returncode == 1, proc.stderr
    assert "no" in proc.stdout


def test_cli_exits_two_on_missing_file(tmp_path):
    proc = _run_cli(tmp_path / "does-not-exist.json")
    assert proc.returncode == 2


def test_cli_exits_two_on_invalid_json(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text("not json", encoding="utf-8")
    proc = _run_cli(f)
    assert proc.returncode == 2
