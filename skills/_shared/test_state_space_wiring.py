"""Structured checks for the state-space wiring across the SKILL.md consumers.

The wording of the SKILL.md files is not pinned here. Every path, script, flag
and skill the four consumers (and the orchestrator) name, including
skills/_shared/state-space-protocol.md and state_space_lint.py, is covered by
invariant 46 (`skill_refs`), run in-suite below. The 500-line cap on each
SKILL.md is invariant 34. The map-check category the audits tag is a code
constant, exercised through the shipped synth-prompt builder.

Run with: pytest skills/_shared/test_state_space_wiring.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parent.parent
REPO_ROOT = SKILLS.parent

CONSUMERS = ["tp-design", "tp-design-audit", "tp-plan-audit", "tp-promote",
             "tp-run-full-design"]


def _shared(name: str):
    shared = str(REPO_ROOT / "skills" / "_shared")
    if shared not in sys.path:
        sys.path.insert(0, shared)
    return pytest.importorskip(name)


@pytest.mark.parametrize("skill", CONSUMERS)
def test_skill_references_resolve(skill, tmp_path):
    """Every reference in the consumer's SKILL.md resolves through invariant 46."""
    skill_refs = _shared("skill_refs")
    if skill == "tp-run-full-design":
        skill_text = _shared("skill_text")
        paths = skill_text.skill_paths(skill)
    else:
        paths = [SKILLS / skill / "SKILL.md"]
    report = skill_refs.check(REPO_ROOT, paths, cache_dir=tmp_path)
    assert report.issues == []


def test_synth_prompt_tags_map_check_category():
    """The audit slots' synth prompt carries the map-check category constant."""
    sys.path.insert(0, str(SKILLS / "tp-run-full-design" / "scripts"))
    import build_synth_prompt as bsp
    assert bsp.MAP_CHECK_SLOTS == {"design-audit", "plan-audit"}
    assert bsp.MAP_CHECK_CATEGORY == "map-check"
