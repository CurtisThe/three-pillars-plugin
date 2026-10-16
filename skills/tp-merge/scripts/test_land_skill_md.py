"""Structured checks for skills/tp-merge/SKILL.md — the land skill.

The wording of the SKILL.md is not pinned here. The frontmatter is checked
through the shipped parser, and every path, script, flag and skill the doc
names is covered by invariant 46 (`skill_refs`), run in-suite below. The
gate behaviour itself (refuse on MergeGateBlocked, `gh pr merge` only on
PASS) is exercised by test_land.py and test_merge_skill_gate_command.py.

Run with: pytest skills/tp-merge/scripts/test_land_skill_md.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"
REPO_ROOT = SKILL_MD.parents[2]


def _shared(name: str):
    shared = str(REPO_ROOT / "skills" / "_shared")
    if shared not in sys.path:
        sys.path.insert(0, shared)
    return pytest.importorskip(name)


def test_frontmatter_valid_and_named_tp_merge() -> None:
    """The retained land name: the frontmatter validates and names tp-merge."""
    skill_frontmatter = _shared("skill_frontmatter")
    assert skill_frontmatter.check(SKILL_MD) == []
    fields, issues = skill_frontmatter.parse(SKILL_MD.read_text(encoding="utf-8"))
    assert issues == []
    assert fields["name"][1] == "tp-merge"  # parse() maps key -> (line, value)
    assert fields["description"][1].strip()


def test_skill_references_resolve(tmp_path) -> None:
    """Every reference in tp-merge/SKILL.md (human-approval-howto.md, land.py,
    seat_resolve.sh, resolve_root.sh, /tp-post-merge, flags) resolves and
    parses through invariant 46's check, run in-suite."""
    skill_refs = _shared("skill_refs")
    report = skill_refs.check(REPO_ROOT, [SKILL_MD], cache_dir=tmp_path)
    assert report.issues == []
