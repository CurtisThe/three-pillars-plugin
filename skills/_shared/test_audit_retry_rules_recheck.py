"""The audit-retry recheck predicates + CLI (design: review-convergence 12.1).

Behavior 18: mediums without a run failure after one patch -> pass-with-notes;
a HIGH -> re-check; CLI exit 0/1; ``lows-only`` unchanged (the companion
module test_audit_retry_rules.py covers it fully; a smoke pair lives here).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_retry_rules  # noqa: E402

MODULE = Path(__file__).resolve().parent / "audit_retry_rules.py"

# Finding lists per detailed-design-phase-check.md §F1: the synth asks for
# severity (critical|medium|minor), file, line and run_failure per finding.
MEDIUMS_NO_RUN_FAILURE = [
    {"severity": "medium", "category": "logic", "file": "a.py", "line": 3, "run_failure": ""},
    {"severity": "medium", "category": "style", "file": "b.py", "line": 9},
]
ONE_CRITICAL = [
    {"severity": "critical", "category": "logic", "file": "a.py", "line": 12,
     "run_failure": "pytest test_a.py - 1 failed"},
]
CRITICAL_MAP_CHECK_ONLY = [
    {"severity": "critical", "category": "map-check", "file": "a.py", "line": 1},
]

OPEN_HIGH_CASES = [
    ("critical non-map-check is open", ONE_CRITICAL, True),
    ("mediums are not open", MEDIUMS_NO_RUN_FAILURE, False),
    ("critical map-check is ignored", CRITICAL_MAP_CHECK_ONLY, False),
    ("map-check critical beside minor is ignored",
     CRITICAL_MAP_CHECK_ONLY + [{"severity": "minor", "category": "style"}], False),
    ("critical beside mediums is open",
     MEDIUMS_NO_RUN_FAILURE + ONE_CRITICAL, True),
    ("missing severity is not open", [{"category": "logic"}], False),
    ("empty list is not open", [], False),
]


@pytest.mark.parametrize(("label", "findings", "expected"), OPEN_HIGH_CASES,
                         ids=[c[0] for c in OPEN_HIGH_CASES])
def test_open_high_table(label, findings, expected):
    assert audit_retry_rules.open_high(findings) is expected


@pytest.mark.parametrize(("label", "findings", "expected"), OPEN_HIGH_CASES,
                         ids=[c[0] for c in OPEN_HIGH_CASES])
def test_recheck_is_open_high(label, findings, expected):
    assert audit_retry_rules.recheck(findings) is expected


def test_high_constant_drives_open_high():
    # Whatever HIGH names, a non-map-check finding with that severity opens.
    finding = {"severity": audit_retry_rules.HIGH, "category": "logic"}
    assert audit_retry_rules.open_high([finding]) is True
    assert audit_retry_rules.recheck([finding]) is True


NOTE_ONLY_CASES = [
    ("minor is a note", {"severity": "minor", "category": "style"}, True),
    ("medium with no run_failure key is a note", {"severity": "medium"}, True),
    ("medium with empty run_failure is a note",
     {"severity": "medium", "run_failure": ""}, True),
    ("medium with a run failure is not a note",
     {"severity": "medium", "run_failure": "pytest test_a.py - 1 failed"}, False),
    ("critical is not a note", {"severity": "critical"}, False),
    ("missing severity is not a note", {"category": "logic"}, False),
]


@pytest.mark.parametrize(("label", "finding", "expected"), NOTE_ONLY_CASES,
                         ids=[c[0] for c in NOTE_ONLY_CASES])
def test_note_only_table(label, finding, expected):
    assert audit_retry_rules.note_only(finding) is expected


VERDICT_CASES = [
    ("mediums without run failure pass with notes", MEDIUMS_NO_RUN_FAILURE, "pass-with-notes"),
    ("a critical triggers a re-check", ONE_CRITICAL, "re-check"),
    ("critical map-check alone passes with notes", CRITICAL_MAP_CHECK_ONLY, "pass-with-notes"),
    ("empty list passes with notes", [], "pass-with-notes"),
    ("all minor passes with notes",
     [{"severity": "minor", "category": "style"}], "pass-with-notes"),
]


@pytest.mark.parametrize(("label", "findings", "expected"), VERDICT_CASES,
                         ids=[c[0] for c in VERDICT_CASES])
def test_verdict_after_patch_table(label, findings, expected):
    assert audit_retry_rules.verdict_after_patch(findings) == expected


def _run_cli(command, payload_or_path):
    args = [sys.executable, str(MODULE), command, "--findings", str(payload_or_path)]
    return subprocess.run(args, capture_output=True, text=True, cwd=str(MODULE.parent))


def _write(tmp_path: Path, payload) -> Path:
    f = tmp_path / "findings.json"
    f.write_text(json.dumps(payload), encoding="utf-8")
    return f


def test_cli_recheck_exits_one_for_mediums_after_patch(tmp_path):
    f = _write(tmp_path, MEDIUMS_NO_RUN_FAILURE)
    proc = _run_cli("recheck", f)
    assert proc.returncode == 1, proc.stderr
    assert "pass-with-notes" in proc.stdout


def test_cli_recheck_exits_zero_for_critical(tmp_path):
    f = _write(tmp_path, ONE_CRITICAL)
    proc = _run_cli("recheck", f)
    assert proc.returncode == 0, proc.stderr
    assert "re-check" in proc.stdout


def test_cli_recheck_ignores_critical_map_check(tmp_path):
    f = _write(tmp_path, CRITICAL_MAP_CHECK_ONLY)
    proc = _run_cli("recheck", f)
    assert proc.returncode == 1, proc.stderr


def test_cli_recheck_accepts_object_form(tmp_path):
    f = _write(tmp_path, {"findings": ONE_CRITICAL})
    proc = _run_cli("recheck", f)
    assert proc.returncode == 0, proc.stderr


def test_cli_recheck_exits_two_on_missing_file(tmp_path):
    proc = _run_cli("recheck", tmp_path / "does-not-exist.json")
    assert proc.returncode == 2


def test_cli_recheck_exits_two_on_invalid_json(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text("not json", encoding="utf-8")
    proc = _run_cli("recheck", f)
    assert proc.returncode == 2


def test_lows_only_cli_unchanged_yes(tmp_path):
    f = _write(tmp_path, [{"severity": "minor", "category": "style"}])
    proc = _run_cli("lows-only", f)
    assert proc.returncode == 0, proc.stderr
    assert "yes" in proc.stdout


def test_lows_only_cli_unchanged_no(tmp_path):
    f = _write(tmp_path, [{"severity": "critical", "category": "logic"}])
    proc = _run_cli("lows-only", f)
    assert proc.returncode == 1, proc.stderr
    assert "no" in proc.stdout
