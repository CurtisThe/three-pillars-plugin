"""Structured check for skills/tp-revert/SKILL.md (landing / bookkeeping / re-land).

The wording of the SKILL.md is not pinned here. Every path, script, flag and
skill it names (deterministic_gate.py, the tp:reverted label, gh calls) is
covered by invariant 46 (`skill_refs`), run in-suite below.

Recipe / depth / flow checks are in test_revert_skill_md.py.

Run with: pytest skills/tp-revert/scripts/test_revert_skill_md_landing.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"


def test_skill_references_resolve(tmp_path) -> None:
    """Every reference in tp-revert/SKILL.md resolves through invariant 46."""
    repo_root = SKILL_MD.parents[2]
    shared = str(repo_root / "skills" / "_shared")
    if shared not in sys.path:
        sys.path.insert(0, shared)
    skill_refs = pytest.importorskip("skill_refs")
    report = skill_refs.check(repo_root, [SKILL_MD], cache_dir=tmp_path)
    assert report.issues == []
