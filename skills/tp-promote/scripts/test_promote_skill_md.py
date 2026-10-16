"""Structured checks for skills/tp-promote/SKILL.md.

The wording of the SKILL.md is not pinned here. Every path, script, flag and
skill it names (first-run.md, validate_design_floor.py, weight_class.py,
/tp-run-full-design, --skip-design) is covered by invariant 46
(`skill_refs`), which this module also runs in-suite over the SKILL.md.

`/tp-promote` is interactive on purpose (no --auto mode), so the frontmatter
check below reads the parsed `argument-hint` field.

Run with: pytest skills/tp-promote/scripts/test_promote_skill_md.py -q
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


def test_skill_references_resolve(tmp_path) -> None:
    """Every reference in tp-promote/SKILL.md resolves and parses through
    invariant 46's check, run in-suite."""
    skill_refs = _shared("skill_refs")
    report = skill_refs.check(REPO_ROOT, [SKILL_MD], cache_dir=tmp_path)
    assert report.issues == []


def test_frontmatter_is_valid_and_non_auto() -> None:
    """The parsed frontmatter validates, names the skill, and the
    argument-hint carries no --auto (invariant 24: tp-promote keeps its
    human confirm gate)."""
    fm = _shared("skill_frontmatter")
    text = SKILL_MD.read_text(encoding="utf-8")
    assert fm.check(SKILL_MD) == []
    fields, _ = fm.parse(text)
    assert fields["name"][1] == "tp-promote"
    hint = fields.get("argument-hint", (0, ""))[1]
    assert "--auto" not in hint  # tp-allow-fragile: the --auto flag name is itself the interface (invariant 24)
