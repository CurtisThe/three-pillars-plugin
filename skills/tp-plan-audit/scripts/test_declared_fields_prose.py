"""test_declared_fields_prose.py — SKILL.md prose pins for the declared fields.

design: consumer-repo-parity (H4, Phase 3, Task 3.6)

The File and Implementation Order fields are now parsed by dedicated
modules (``plan_files.py``, ``design_phases.py``) instead of being lenient
free text. Each SKILL.md that documents or relies on those fields must name
the parser that reads it, and the `/tp-phase-implement` preflight must tell
the user the WARN count comes from `warn_count`.

Run with: pytest skills/tp-plan-audit/scripts/test_declared_fields_prose.py -q
"""
from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TP_PLAN = _REPO_ROOT / "skills" / "tp-plan" / "SKILL.md"
_TP_DESIGN_DETAIL = _REPO_ROOT / "skills" / "tp-design-detail" / "SKILL.md"
_TP_PHASE_IMPLEMENT = _REPO_ROOT / "skills" / "tp-phase-implement" / "SKILL.md"
_TP_PLAN_AUDIT = _REPO_ROOT / "skills" / "tp-plan-audit" / "SKILL.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_tp_plan_names_plan_files_parser():
    text = _read(_TP_PLAN)
    assert "plan_files.py" in text, "tp-plan/SKILL.md must name plan_files.py"
    # Beside the Targets grammar section.
    assert "Targets field" in text


def test_tp_plan_template_file_line_has_new_and_modify_per_item():
    text = _read(_TP_PLAN)
    assert "`<path/to/file>` (new)" in text
    assert "(modify)" in text


def test_tp_design_detail_names_design_phases_parser():
    text = _read(_TP_DESIGN_DETAIL)
    assert "design_phases.py" in text, (
        "tp-design-detail/SKILL.md §Implementation Order must name design_phases.py"
    )


def test_tp_design_detail_template_uses_numbered_bold_form():
    text = _read(_TP_DESIGN_DETAIL)
    assert "1. **<Phase Title>**" in text
    assert "keep this shape" in text


def test_tp_phase_implement_0b_names_warn_count():
    text = _read(_TP_PHASE_IMPLEMENT)
    assert "warn_count" in text, "tp-phase-implement/SKILL.md 0b must name warn_count"
    assert "audit_artifact.py --check" in text
    assert "/tp-plan-audit" in text


def test_tp_plan_audit_names_both_parsers():
    text = _read(_TP_PLAN_AUDIT)
    assert "plan_files.py" in text, "tp-plan-audit/SKILL.md must name plan_files.py"
    assert "design_phases.py" in text, "tp-plan-audit/SKILL.md must name design_phases.py"


def test_tp_plan_audit_skill_md_under_line_cap():
    lines = _read(_TP_PLAN_AUDIT).splitlines()
    assert len(lines) <= 328, f"tp-plan-audit/SKILL.md is {len(lines)} lines, cap is 328"
