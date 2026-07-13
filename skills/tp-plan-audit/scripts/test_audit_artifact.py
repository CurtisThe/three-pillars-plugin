"""Tests for the plan-audit pass-artifact contract (audit_artifact.py)."""

import re
import sys
import json
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_artifact  # noqa: E402

SCRIPT = Path(__file__).resolve().parent / "audit_artifact.py"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _write_plan(design_dir, body):
    (design_dir / "plan.md").write_text(body)


def test_write_then_status_ok(tmp_path):
    _write_plan(tmp_path, "# Plan\n\n### Task 1.1: do the thing\n")
    record = audit_artifact.write_pass_artifact(tmp_path, "light")

    # Returned record + on-disk JSON agree and carry the contract fields.
    on_disk = json.loads((tmp_path / ".plan-audit-pass.json").read_text(encoding="utf-8"))
    assert on_disk == record
    assert record["verdict"] == "pass"
    assert record["plan_audit_mode"] == "light"
    assert HEX64.match(record["plan_digest"])
    # audited_at parses as ISO-8601.
    from datetime import datetime

    datetime.fromisoformat(record["audited_at"])

    status, _reason = audit_artifact.artifact_status(tmp_path)
    assert status == "ok"


def test_stale_absent_and_check_cli(tmp_path):
    # Absent: no artifact at all.
    _write_plan(tmp_path, "# Plan\n\n### Task 1.1: do the thing\n")
    assert audit_artifact.artifact_status(tmp_path)[0] == "absent"
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--check", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert r.returncode != 0
    assert "/tp-plan-audit" in r.stdout

    # Current pass: write artifact, --check exits 0.
    audit_artifact.write_pass_artifact(tmp_path, "light")
    assert audit_artifact.artifact_status(tmp_path)[0] == "ok"
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--check", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0

    # Stale: plan.md bytes change after the artifact was written.
    _write_plan(tmp_path, "# Plan changed\n\n### Task 1.1: different\n")
    assert audit_artifact.artifact_status(tmp_path)[0] == "stale"
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--check", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert r.returncode != 0
    assert "/tp-plan-audit" in r.stdout


def test_plan_digest_detects_any_byte_change(tmp_path):
    # The load-bearing property: two byte-different plan.md contents must yield
    # two different 64-char-hex digests so ANY content change is detectable.
    p = tmp_path / "plan.md"
    p.write_text("# Plan A\n")
    d1 = audit_artifact.plan_digest(p)
    p.write_text("# Plan B\n")
    d2 = audit_artifact.plan_digest(p)
    assert HEX64.match(d1) and HEX64.match(d2)
    assert d1 != d2


def test_forged_nonpass_verdict_refused(tmp_path):
    # Defense-in-depth: a hand-forged artifact with a MATCHING digest but a
    # non-"pass" verdict must NOT satisfy the gate (verdict is load-bearing).
    _write_plan(tmp_path, "# Plan\n\n### Task 1.1: t\n")
    digest = audit_artifact.plan_digest(tmp_path / "plan.md")
    (tmp_path / ".plan-audit-pass.json").write_text(
        json.dumps({"verdict": "fail", "plan_digest": digest,
                    "plan_audit_mode": "light", "audited_at": "2026-01-01T00:00:00+00:00"})
    )
    status, _reason = audit_artifact.artifact_status(tmp_path)
    assert status != "ok"
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--check", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert r.returncode != 0
    assert "/tp-plan-audit" in r.stdout


def test_nondict_json_is_absent_not_crash(tmp_path):
    # A parseable-but-non-dict artifact (list/number/string) must read as
    # absent (fail-closed) WITHOUT an uncaught AttributeError traceback.
    _write_plan(tmp_path, "# Plan\n\n### Task 1.1: t\n")
    for blob in ('["pass"]', "5", '"pass"'):
        (tmp_path / ".plan-audit-pass.json").write_text(blob)
        assert audit_artifact.read_pass_artifact(tmp_path) is None
        assert audit_artifact.artifact_status(tmp_path)[0] == "absent"
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--check", str(tmp_path)],
            capture_output=True, text=True,
        )
        assert r.returncode != 0
        assert "Traceback" not in (r.stderr + r.stdout)
