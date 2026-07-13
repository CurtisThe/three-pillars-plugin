"""Grep-level lint over skills/tp-plan/SKILL.md — the per-phase budget-awareness
contract (Task 7.1).

Each emitted plan.md phase header must carry a `(~Nk)` budget annotation and stay
under the 200k per-phase cap — the `phase-implement` slot's soft budget from
tp-run-full-design's static budget table (each plan phase is dispatched under one
phase-implement slot, so the table value is authoritative). These asserts pin the
load-bearing literals so the contract survives future prose edits.
"""
from __future__ import annotations

from pathlib import Path

SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"


def _body() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def test_phase_header_budget_annotation_documented():
    body = _body()
    # tp-plan must instruct each emitted plan.md phase header to carry a (~Nk)
    # token-budget annotation.
    assert "(~Nk)" in body, (
        "tp-plan must instruct each plan.md phase header to carry a (~Nk) "
        "budget annotation"
    )
    assert "phase header" in body.lower(), (
        "the (~Nk) annotation attaches to the phase header"
    )


def test_per_phase_cap_referenced():
    body = _body()
    # The per-phase cap of 200k, sourced from the phase-implement slot's budget.
    assert "200k" in body, "the per-phase cap of 200k must be documented"
    assert "phase-implement" in body, (
        "the cap must be tied to the phase-implement slot's soft budget"
    )
    # Reference the static budget table rather than re-deriving the number.
    assert "budget table" in body.lower(), (
        "the cap must reference tp-run-full-design's static budget table as "
        "the authoritative source for the 200k value"
    )


def test_phase_format_template_carries_annotation():
    body = _body()
    # The plan.md format template itself shows the annotation on a Phase header,
    # so the generator emits it by example (not just by instruction).
    assert "## Phase 1:" in body, "the plan.md format template must show a Phase header"
    # A templated phase header line carries the (~Nk) token.
    template_lines = [
        ln for ln in body.splitlines()
        if ln.lstrip().startswith("## Phase") and "(~Nk)" in ln
    ]
    assert template_lines, (
        "at least one templated '## Phase N:' header must carry the (~Nk) annotation"
    )
