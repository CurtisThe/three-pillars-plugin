"""test_pending_changes_low.py — fix.5: the dry-run fold sees the Low parts.

design: living-doc-fragments, fidelity-audit fix 5. ``pending_changes.summary`` dry-folds the fragments
onto the docs on disk; a fragment resolving a Low issue must fold against ``known_issues_low*.md`` as the
real compile does, not report a false ``no entry`` conflict.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pending_changes  # noqa: E402

DOCS = "three-pillars-docs/"


def _write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo(tmp_path, low_rel):
    _write(tmp_path, DOCS + "known_issues.md", "# Known Issues\n\n## Medium\n\n## Low\n")
    _write(tmp_path, low_rel, "# Known Issues — Low\n\n## Low\n\n### L139: a low issue\nbody\n")
    _write(tmp_path, DOCS + "changes/demo.md",
           "---\nslug: demo\nkind: design\ndate: 2026-10-22\n---\n\n"
           "## Known issues — resolve\n\n- L139: fixed by the demo design\n")


def test_fragment_resolving_a_low_issue_has_no_conflict(tmp_path):
    _repo(tmp_path, DOCS + "known_issues_low.md")
    assert "conflict" not in pending_changes.summary(tmp_path)


def test_a_later_low_part_is_read_too(tmp_path):
    _repo(tmp_path, DOCS + "known_issues_low_2.md")
    assert "conflict" not in pending_changes.summary(tmp_path)


def test_a_truly_missing_entry_still_conflicts(tmp_path):
    _repo(tmp_path, DOCS + "known_issues_low.md")
    _write(tmp_path, DOCS + "changes/demo.md",
           "---\nslug: demo\nkind: design\ndate: 2026-10-22\n---\n\n"
           "## Known issues — resolve\n\n- L999: no such entry\n")
    assert "conflict" in pending_changes.summary(tmp_path)
