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
