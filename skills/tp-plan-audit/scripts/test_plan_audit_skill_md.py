"""test_plan_audit_skill_md.py — SKILL.md pin tests for tp-plan-audit.

plugin-mode-parity Task 3.8 expansion — [N2]: Step 2's audit_plan.py
invocation used the legacy ~/.claude/skills/ personal-install path (a
location the plugin never creates) with a "project-installed" fallback
sentence describing a since-superseded install topology. Both are replaced
by the $TP_ROOT anchor every other executable reference in this SKILL.md
already uses (D7 PATH fix pattern).

Run with: pytest skills/tp-plan-audit/scripts/test_plan_audit_skill_md.py -q
"""
from __future__ import annotations

from pathlib import Path

_SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"


def _read() -> str:
    return _SKILL_MD.read_text(encoding="utf-8")


def test_audit_plan_invocation_is_tp_root_anchored():
    """audit_plan.py must be invoked via the $TP_ROOT anchor, not a legacy install path."""
    text = _read()
    assert "~/.claude/skills/tp-plan-audit/scripts/audit_plan.py" not in text, (
        "the legacy ~/.claude/skills/ path must be gone from the audit_plan.py invocation"
    )
    assert '"$TP_ROOT"/skills/tp-plan-audit/scripts/audit_plan.py' in text, (
        'audit_plan.py must be invoked via python3 "$TP_ROOT"/skills/tp-plan-audit/scripts/audit_plan.py'
    )


def test_no_project_installed_fallback_sentence():
    """The since-superseded '.claude/skills/...' project-install fallback sentence must be gone."""
    text = _read()
    assert ".claude/skills/tp-plan-audit/scripts/audit_plan.py" not in text, (
        "the '.claude/skills/...' project-installed fallback path must be removed "
        "($TP_ROOT already resolves correctly across dev/project/plugin installs)"
    )
