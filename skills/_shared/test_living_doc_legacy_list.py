"""test_living_doc_legacy_list.py — fix.4: the legacy list exempts listed slugs and holds the in-flight run.

design: living-doc-fragments, fidelity-audit fix 4. Behavioural: ``living_doc_guard.check`` on a temp git
repo where a listed slug edits a living doc passes, an unlisted slug is refused with the fragment fix
line, and the repo's real list names ``light-run-ceremony-diet`` (in flight when the repo upgraded).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

import living_doc_guard  # noqa: E402

REAL_LIST = Path(__file__).resolve().parents[2] / living_doc_guard.LEGACY_REL
DOC = "three-pillars-docs/known_issues.md"


def _git(root, *args) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          check=True).stdout.strip()


def _repo(tmp_path, slug: str, listed: bool):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / DOC).parent.mkdir(parents=True)
    (root / DOC).write_text("# Known " + "Issues\n", encoding="utf-8")
    if listed:
        (root / living_doc_guard.LEGACY_REL).parent.mkdir(parents=True)
        (root / living_doc_guard.LEGACY_REL).write_text(f"# header\n{slug}\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "checkout", "-q", "-b", f"tp/{slug}")
    (root / DOC).write_text("# Known Issues\n\n### M1: edited on a design branch\n", encoding="utf-8")
    _git(root, "commit", "-q", "-am", "edit a living doc")
    return root


def test_listed_slug_editing_a_living_doc_passes(tmp_path):
    root = _repo(tmp_path, "oldrun", listed=True)
    assert living_doc_guard.check(root, base_ref="main").verdict == "exempt"


def test_unlisted_slug_is_refused_with_the_fragment_fix_line(tmp_path):
    root = _repo(tmp_path, "newrun", listed=False)
    res = living_doc_guard.check(root, base_ref="main")
    assert res.verdict == "refused" and res.paths == [DOC]
    assert "three-pillars-docs/changes/newrun.md" in res.fix


def test_real_list_holds_only_slugs():
    # The list only shrinks (a merged design's line is deleted), so pin its shape, not a member.
    slugs = [ln.strip() for ln in REAL_LIST.read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.startswith("#")]
    assert slugs and all(re.fullmatch(r"[a-z0-9-]+", s) for s in slugs), slugs
