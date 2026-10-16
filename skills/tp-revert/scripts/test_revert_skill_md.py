"""Structured checks for skills/tp-revert/SKILL.md.

The wording of the SKILL.md is not pinned here. Every path, script, flag and
skill it names is covered by invariant 46 (`skill_refs`), which this module
also runs in-suite over the SKILL.md. The depth and conflict behaviour the
skill relies on is tested on the probe itself (`test_revert_probe.py`,
`test_revert_probe_forecast.py`).

Landing / bookkeeping / re-land prose tests are in test_revert_skill_md_landing.py.

Run with: pytest skills/tp-revert/scripts/test_revert_skill_md.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"


def test_skill_references_resolve(tmp_path) -> None:
    """Every reference in tp-revert/SKILL.md (reconcile-protocol.md,
    living-doc-format.md, reconcile_docs.py, known_issues.md, flags) resolves
    and parses through invariant 46's check, run in-suite."""
    repo_root = SKILL_MD.parents[2]
    shared = str(repo_root / "skills" / "_shared")
    if shared not in sys.path:
        sys.path.insert(0, shared)
    skill_refs = pytest.importorskip("skill_refs")
    report = skill_refs.check(repo_root, [SKILL_MD], cache_dir=tmp_path)
    assert report.issues == []
