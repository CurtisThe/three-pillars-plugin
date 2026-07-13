"""Prose test: tp-test-setup SKILL.md step 8 documents the demos/scratch hatch.

Asserts that the shipped gitignore guidance in tp-test-setup agrees with the
repo .gitignore scratch-hatch added in Task 1.1. The SKILL.md must:
  - mention demos/scratch/ as the throwaway hatch
  - use the literal pattern three-pillars-docs/tp-designs/*/demos/scratch/
  - state that demos/ proper stays tracked while scratch/ + *.tmp are the hatch

Contract source: spike-evidence-versioning Task 1.2.

Run with: python -m pytest skills/_shared/test_test_setup_gitignore_template.py -q
"""

from pathlib import Path


def _skill_md_text() -> str:
    root = Path(__file__).parent.parent.parent  # repo root
    skill_path = root / "skills" / "tp-test-setup" / "SKILL.md"
    return skill_path.read_text(encoding="utf-8")


def test_scratch_hatch_pattern_present():
    """SKILL.md step 8 includes the demos/scratch/ gitignore pattern."""
    text = _skill_md_text()
    assert "demos/scratch/" in text, (
        "skills/tp-test-setup/SKILL.md step 8 must include the literal "
        "'demos/scratch/' pattern. Add the scratch-hatch documentation."
    )


def test_tp_designs_scratch_pattern_present():
    """SKILL.md documents the full scoped pattern for tp-designs."""
    text = _skill_md_text()
    assert "three-pillars-docs/tp-designs/*/demos/scratch/" in text, (
        "skills/tp-test-setup/SKILL.md must include the full scoped pattern "
        "'three-pillars-docs/tp-designs/*/demos/scratch/'. "
        "Add it to the .gitignore block in step 8."
    )


def test_tmp_hatch_pattern_present():
    """SKILL.md documents the *.tmp escape hatch for demos/."""
    text = _skill_md_text()
    assert "*.tmp" in text, (
        "skills/tp-test-setup/SKILL.md step 8 must document the *.tmp hatch. "
        "Add the pattern to the .gitignore block."
    )


def test_scratch_framed_as_throwaway_hatch():
    """SKILL.md uses the word 'scratch' in the context of a throwaway hatch."""
    text = _skill_md_text()
    assert "scratch" in text.lower(), (
        "skills/tp-test-setup/SKILL.md must mention 'scratch' as the throwaway "
        "hatch for demos/. Add explanatory text alongside the pattern."
    )


def test_demos_tracked_note_present():
    """SKILL.md step 8 notes that demos/ proper stays tracked (not fully gitignored)."""
    text = _skill_md_text()
    lower = text.lower()
    # The note should convey demos are tracked EXCEPT scratch
    has_demos_tracked = (
        "demos/" in text
        and ("tracked" in lower or "evidence" in lower)
        and "scratch" in lower
    )
    assert has_demos_tracked, (
        "skills/tp-test-setup/SKILL.md step 8 must state that demos/ proper is "
        "tracked evidence while scratch/ + *.tmp are the throwaway hatch. "
        "Update the step-8 Note."
    )


def test_handoff_pattern_still_present():
    """Regression: the existing handoff.md pattern is still documented in step 8."""
    text = _skill_md_text()
    assert "three-pillars-docs/tp-designs/*/handoff.md" in text, (
        "Regression: the existing handoff.md pattern must remain in "
        "skills/tp-test-setup/SKILL.md step 8."
    )
