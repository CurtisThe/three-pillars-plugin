"""Structured checks for skills/tp-post-merge/SKILL.md.

The wording of the SKILL.md is not pinned here. Every path, script, flag and
skill it names is covered by invariant 46 (`skill_refs`), which this module
also runs in-suite over the SKILL.md.

(The Phase-1 `cleanup-pending` enum assertion lives in its own self-contained
file, `test_collaboration_phase_enum.py`.)

Run with: pytest skills/tp-post-merge/scripts/test_post_merge_skill_md.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"


def test_skill_references_resolve(tmp_path) -> None:
    """Every reference in tp-post-merge/SKILL.md (first-run.md, auto-mode.md,
    gc_candidate_branches.py, sweep_candidates.py, reconcile_docs.py, flags)
    resolves and parses through invariant 46's check, run in-suite."""
    repo_root = SKILL_MD.parents[2]
    shared = str(repo_root / "skills" / "_shared")
    if shared not in sys.path:
        sys.path.insert(0, shared)
    skill_refs = pytest.importorskip("skill_refs")
    report = skill_refs.check(repo_root, [SKILL_MD], cache_dir=tmp_path)
    assert report.issues == []


def _step4() -> str:
    lines = SKILL_MD.read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("4. **Verify merge**"))
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("5. "))
    return "\n".join(lines[start:end])


def test_step4_names_ancestor_and_refusal_checks() -> None:
    step = _step4()
    for word in ("ancestor", "checks", "remedy"):
        assert word in step


def test_step_4b_scratch_check_wired() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    assert text.count("\n4b. ") == 1
    i = text.index("\n4b. ")
    assert text.index("\n4. **Verify merge**") < i < text.index("\n5. **Teardown**")
    assert "scratch_leftovers.py check --slug {name}" in text[i:text.index("\n5. **Teardown**")]
