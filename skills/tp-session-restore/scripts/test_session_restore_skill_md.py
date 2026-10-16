"""Structured checks for skills/tp-session-restore/SKILL.md.

The restore-completed-design-lookup wording is not pinned here; every path,
script and skill the SKILL names is checked by `skill_refs` (invariant 46).

Run with: pytest skills/tp-session-restore/scripts/test_session_restore_skill_md.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SHARED = str(Path(__file__).resolve().parents[2] / "_shared")
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"


def test_skill_refs_clean(tmp_path):
    skill_refs = pytest.importorskip("skill_refs")
    assert skill_refs.check(REPO_ROOT, [SKILL_MD], cache_dir=tmp_path).issues == []
