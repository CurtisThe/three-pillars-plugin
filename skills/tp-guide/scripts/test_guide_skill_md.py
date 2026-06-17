"""Grep invariants for `/tp-guide` SKILL.md (Phase 6 of parallel-design-worktrees).

Two tests:
- Section `## Other worktrees in flight` is present.
- The section mentions reading per-worktree `state.json` so the cross-
  worktree dashboard knows its data source.

Run with: pytest skills/tp-guide/scripts/test_guide_skill_md.py -q
"""

from __future__ import annotations

from pathlib import Path

SKILL_MD = Path(__file__).parent.parent / "SKILL.md"


def _read() -> str:
    return SKILL_MD.read_text()


def test_other_worktrees_section_present() -> None:
    assert "## Other worktrees in flight" in _read(), (
        "Phase 6 Task 6.1 — section header must be present"
    )


def test_reads_state_json_per_worktree() -> None:
    assert "state.json" in _read(), (
        "the Other-worktrees section must name the data source `state.json`"
    )


def test_weight_class_table() -> None:
    """design-depth-axis Task 2.1 — step-7 four-class table + step-8 class line."""
    text = _read()
    # Four-class table rows, one per weight class.
    for klass in ("Just do it", "Light", "Spike", "Full"):
        assert f"**{klass}" in text, f"step-7 table must have a {klass!r} row"
    # References the rubric axes and the protocol doc.
    for axis in ("risk", "blast radius", "reversibility", "novelty"):
        assert axis in text.lower(), f"step 7 must reference the {axis!r} rubric axis"
    assert "skills/_shared/weight-class.md" in text, (
        "step 7 must point at the weight-class protocol doc"
    )
    # Synthesis step requires class + one-line justification.
    assert "weight class" in text.lower()
    assert "justification" in text.lower(), (
        "step 8 must require a class + one-line justification in the recommendation"
    )
