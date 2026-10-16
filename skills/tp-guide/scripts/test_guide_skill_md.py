"""Structured check for `/tp-guide` SKILL.md.

The SKILL.md prose (section headings, weight-class table wording, `state.json`
mention) is not asserted here. The doc's references (paths such as
`skills/_shared/weight-class.md`, helper scripts, flags, skills) are checked by
`skill_refs` (invariant 46).

Run with: pytest skills/tp-guide/scripts/test_guide_skill_md.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"
REPO_ROOT = SKILL_MD.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "skills" / "_shared"))


def test_guide_skill_references_resolve(tmp_path):
    """Every path, helper script and `/tp-*` skill SKILL.md names exists."""
    skill_refs = pytest.importorskip("skill_refs")
    assert SKILL_MD.exists()
    assert skill_refs.check(REPO_ROOT, [SKILL_MD], cache_dir=tmp_path).issues == []
