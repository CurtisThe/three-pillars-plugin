"""M46 / M25: Slot 6 records its council pass as `.plan-audit-pass.json`.

Slot 6 runs its own council fan-out and never calls `/tp-plan-audit`, so before this
fix an autonomous run had no pass artifact and `/tp-phase-implement` step 0b refused.
The orchestrator now runs `audit_artifact.py --write … --mode council` after a pass.
These tests pull that command out of `throughput.md` and run it, so a doc that names
a broken command fails here, not in a live run.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

import skill_text  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parent.parent
TP_ROOT = SKILL_DIR.parent.parent
THROUGHPUT_MD = SKILL_DIR / "throughput.md"
SKILL_MD = SKILL_DIR / "SKILL.md"
ARTIFACT = ".plan-audit-pass.json"


def _flat(text: str) -> str:
    return " ".join(text.split())


def _prechecks() -> str:
    text = THROUGHPUT_MD.read_text(encoding="utf-8")
    start = text.index("\n## Plan-audit prechecks\n")
    end = text.find("\n## ", start + 1)
    return text[start:end]


def _write_command() -> str:
    spans = re.findall(r"`(python3 [^`\n]*audit_artifact\.py --write [^`\n]*)`", _prechecks())
    assert len(spans) == 1, spans
    return spans[0]


def test_prechecks_section_says_when_slot6_writes_the_artifact():
    sec = _flat(_prechecks())
    assert "`pass-with-notes`" in sec and "`pass`" in sec
    assert "before Slot 7" in sec
    assert "`write_pass_artifact`" in sec
    assert "light" in sec, "the merged Slots 4+6 pass under light writes it too"


def test_write_command_uses_the_shared_helper_in_council_mode():
    cmd = _write_command()
    assert cmd.startswith('python3 "$TP_ROOT"/skills/tp-plan-audit/scripts/audit_artifact.py --write ')
    assert cmd.endswith(" --mode council")
    assert "three-pillars-docs/tp-designs/{slug}" in cmd


def test_documented_command_writes_a_current_artifact(tmp_path):
    design = tmp_path / "three-pillars-docs" / "tp-designs" / "demo"
    design.mkdir(parents=True)
    (design / "plan.md").write_text("# Plan\n\n### Task 1.1: x\n**File**: `a.py` (new)\n",
                                    encoding="utf-8")
    cmd = _write_command().replace("{slug}", "demo")
    r = subprocess.run(["bash", "-c", cmd], cwd=tmp_path, capture_output=True, text=True,
                       env={"TP_ROOT": str(TP_ROOT), "PATH": "/usr/bin:/bin"})
    assert r.returncode == 0, r.stderr
    rec = json.loads((design / ARTIFACT).read_text(encoding="utf-8"))
    assert rec["verdict"] == "pass" and rec["plan_audit_mode"] == "council"
    check = subprocess.run(
        ["python3", str(TP_ROOT / "skills/tp-plan-audit/scripts/audit_artifact.py"),
         "--check", str(design)], capture_output=True, text=True)
    assert check.returncode == 0, check.stdout


def test_skill_md_slot6_points_at_the_artifact_write():
    skill = skill_text.read_skill_text("tp-run-full-design")
    slot6 = skill.split("\n### Slot 6 — `plan-audit`\n", 1)[1].split("\n### ", 1)[0]
    assert ARTIFACT in slot6 and "throughput.md" in slot6


def test_tier2_table_no_longer_names_a_plan_audit_subagent():
    """M25's drift: read literally, the old row implied /tp-plan-audit wrote the artifact."""
    skill = skill_text.read_skill_text("tp-run-full-design")
    assert "| 6 — `plan-audit` | `/tp-plan-audit {slug} --auto` |" not in skill
    assert "- **`/tp-plan-audit --auto`** —" not in skill
