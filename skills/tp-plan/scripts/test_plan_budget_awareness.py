"""Per-phase budget-awareness contract for tp-plan (Task 7.1, converted in 24.4).

Each emitted plan.md phase header must carry a `(~Nk)` budget annotation and stay
under the 200k per-phase cap. The contract is checked through the shipped
validator (`audit_plan.check_budget_annotations`) over the phase headers of the
SKILL.md's plan template, read as parsed code spans (skill_spans), never as prose.
Path/script references are covered by skill_refs (invariant 46).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"
_SKILLS = Path(__file__).resolve().parents[2]
_SHARED = _SKILLS / "_shared"
_AUDIT = _SKILLS / "tp-plan-audit" / "scripts"


def _import(name: str, *dirs: Path):
    for d in dirs:
        if str(d) not in sys.path:
            sys.path.insert(0, str(d))
    return pytest.importorskip(name)


def _template_headers() -> list[str]:
    """Phase header lines of the SKILL.md plan template, from the parsed code spans."""
    skill_spans = _import("skill_spans", _SHARED)
    text = _SKILL_MD.read_text(encoding="utf-8")
    return [
        span.strip()
        for _, span, _ in skill_spans.code_spans(text)
        if span.lstrip().startswith("## Phase")
    ]


def test_template_phase_headers_carry_annotation():
    """Every templated phase header, once its N is filled in, passes the validator;
    without the annotation the validator flags it."""
    audit = _import("audit_plan", _SHARED, _AUDIT)
    headers = _template_headers()
    assert len(headers) >= 2
    for h in headers:
        filled = h.replace("(~Nk)", "(~50k)")
        assert audit.check_budget_annotations(filled) == [], h
        bare = filled.replace(" (~50k)", "")
        assert bare != filled, f"template header has no annotation: {h}"
        assert audit.check_budget_annotations(bare), f"validator must flag: {bare}"


def test_per_phase_cap_is_200k():
    """The validator's cap is 200k and a phase over it is flagged (200k passes)."""
    audit = _import("audit_plan", _SHARED, _AUDIT)
    assert audit.PER_PHASE_BUDGET_CAP_K == 200
    assert audit.check_budget_annotations("## Phase 1: A (~200k)\n") == []
    assert audit.check_budget_annotations("## Phase 1: A (~201k)\n")


def test_skill_refs_clean():
    """The SKILL.md this module covered resolves every reference (invariant 46)."""
    skill_refs = _import("skill_refs", _SHARED)
    report = skill_refs.check(_SKILLS.parent, [_SKILL_MD])
    assert report.issues == []
