"""Phase 2 Task 2.1 — pin the distinct audit-phase tokens across the enum and
the four emit sites (CI-collected because this file lives under skills/_shared/).

Run with: pytest skills/_shared/test_audit_phase_tokens.py -q
"""

from __future__ import annotations

import re
from pathlib import Path


_SHARED_DIR = Path(__file__).resolve().parent
_SKILLS_DIR = Path(__file__).resolve().parents[1]

COLLAB_MD = _SHARED_DIR / "collaboration.md"
DESIGN_AUDIT_SKILL = _SKILLS_DIR / "tp-design-audit" / "SKILL.md"
IMPLEMENTATION_AUDIT_SKILL = _SKILLS_DIR / "tp-implementation-audit" / "SKILL.md"
SPIKE_RESULTS_SKILL = _SKILLS_DIR / "tp-spike-results" / "SKILL.md"
PLAN_AUDIT_SKILL = _SKILLS_DIR / "tp-plan-audit" / "SKILL.md"

_EMIT_SITE_SKILLS = (
    DESIGN_AUDIT_SKILL,
    IMPLEMENTATION_AUDIT_SKILL,
    SPIKE_RESULTS_SKILL,
    PLAN_AUDIT_SKILL,
)

# Mirrors the pipe-delimited "phase" enum matcher in the sibling
# skills/tp-post-merge/scripts/test_collaboration_phase_enum.py.
_PHASE_ENUM_RE = re.compile(r'"phase"\s*:\s*"([^"]*)"')

_BARE_AUDIT_RE = re.compile(r'phase:\s*"audit"')


def test_collaboration_enum_has_distinct_tokens_and_retains_audit() -> None:
    text = COLLAB_MD.read_text(encoding="utf-8")
    matches = _PHASE_ENUM_RE.findall(text)
    assert matches, "skills/_shared/collaboration.md must document the lock.json \"phase\" enum"
    enum_values = {v.strip() for m in matches for v in m.split("|")}
    distinct_audit_tokens = {
        "design-audit",
        "plan-audit",
        "implementation-audit",
        "spike-plan-audit",
        "spike-results",
    }
    missing = distinct_audit_tokens - enum_values
    assert not missing, (
        "skills/_shared/collaboration.md must include the distinct audit-phase "
        f"tokens in the lock.json phase enum (missing: {sorted(missing)})"
    )
    assert "audit" in enum_values, (
        "skills/_shared/collaboration.md must retain 'audit' as a deprecated "
        "legacy alias in the lock.json phase enum"
    )


def test_design_audit_emits_distinct_token() -> None:
    text = DESIGN_AUDIT_SKILL.read_text(encoding="utf-8")
    assert 'phase: "design-audit"' in text, (
        "skills/tp-design-audit/SKILL.md must emit phase: \"design-audit\""
    )


def test_implementation_audit_emits_distinct_token() -> None:
    text = IMPLEMENTATION_AUDIT_SKILL.read_text(encoding="utf-8")
    assert 'phase: "implementation-audit"' in text, (
        "skills/tp-implementation-audit/SKILL.md must emit phase: \"implementation-audit\""
    )


def test_spike_results_emits_distinct_token() -> None:
    text = SPIKE_RESULTS_SKILL.read_text(encoding="utf-8")
    assert 'phase: "spike-results"' in text, (
        "skills/tp-spike-results/SKILL.md must emit phase: \"spike-results\""
    )


def test_plan_audit_emits_both_mode_conditional_tokens() -> None:
    text = PLAN_AUDIT_SKILL.read_text(encoding="utf-8")
    assert 'phase: "plan-audit"' in text, (
        "skills/tp-plan-audit/SKILL.md must emit phase: \"plan-audit\" for code-ladder mode"
    )
    assert 'phase: "spike-plan-audit"' in text, (
        "skills/tp-plan-audit/SKILL.md must emit phase: \"spike-plan-audit\" for --spike mode"
    )


def test_no_emit_site_still_writes_bare_audit() -> None:
    offenders = [
        str(path) for path in _EMIT_SITE_SKILLS if _BARE_AUDIT_RE.search(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        f"these SKILL.md files still emit the deprecated bare phase: \"audit\": {offenders}"
    )
