"""test_commit_guard_prose.py — Task 9.6: commit-guard prose corrections.

consumer-repo-parity, part E §Prose corrections.

Pins, by token / key only (never prose sentences):
  1. No non-test file under `skills/` or `agents/` contains a `CLAUDE.md §File
     Size Limits` citation — every shipped claim of commit-time enforcement
     must name the shipped runner (`commit_guard.py` / `hot_patch_check.py`)
     or say "only when the commit guard is installed", and every caps
     citation must point at the shipped `skills/_shared/file-size-caps.md`
     doc instead of `CLAUDE.md`.
  2. The five SKILL/agent docs that used to cite `CLAUDE.md §File Size
     Limits` now cite `file-size-caps.md`.
  3. The docs that claim commit-time enforcement now name `commit_guard.py`
     (or `hot_patch_check.py` for the hot-patch lines).
  4. `cwd_preflight.py`'s docstring no longer cites the retired `#28`.

The `§File Size Limits` token is built from pieces below so this test file
itself never carries the literal contiguous token (it would otherwise flag
itself if the scan were ever loosened to include test files).

Run with: python3 -m pytest skills/_shared/test_commit_guard_prose.py
"""
from __future__ import annotations

from pathlib import Path

import skill_text

_SHARED = Path(__file__).resolve().parent
_SKILLS = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[2]
_AGENTS = _REPO_ROOT / "agents"

# Built from pieces so this file never carries the literal token contiguously.
_SECTION_TOKEN = "§" + "File Size Limits"

_FIVE_DOCS = (
    _SKILLS / "tp-plan" / "SKILL.md",
    _SKILLS / "tp-design-detail" / "SKILL.md",
    _SKILLS / "tp-phase-implement" / "SKILL.md",
    _SKILLS / "tp-run-full-design" / "SKILL.md",
    _AGENTS / "tp-task-worker.md",
)

_COMMIT_GUARD_DOCS = (
    _SHARED / "cwd-preflight.md",
    _SHARED / "collaboration.md",
    _SHARED / "topology.md",
    _SHARED / "commit-after-work.md",
    _SHARED / "weight-class.md",
    _SHARED / "first-run.md",
    _SKILLS / "tp-revert" / "SKILL.md",
    _SKILLS / "tp-phase-implement" / "SKILL.md",
)

# commit-after-work.md and weight-class.md may satisfy the check via the
# hot-patch runner instead of the commit guard's own name.
_HOT_PATCH_OK = {
    _SHARED / "commit-after-work.md",
    _SHARED / "weight-class.md",
}


def _is_probably_text(path: Path) -> bool:
    try:
        path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return False
    return True


def _iter_scanned_files():
    for root in (_SKILLS, _AGENTS):
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts:
                continue
            if path.name.startswith("test_"):
                continue
            if not _is_probably_text(path):
                continue
            yield path


def test_no_shipped_file_carries_the_section_token():
    """No non-test file under skills/ or agents/ carries the §File Size Limits token."""
    offenders = []
    for path in _iter_scanned_files():
        text = path.read_text(encoding="utf-8")
        if _SECTION_TOKEN in text:
            offenders.append(str(path.relative_to(_REPO_ROOT)))
    assert offenders == [], (
        f"shipped files still cite the retired CLAUDE.md section token: {offenders}"
    )


def test_five_docs_cite_the_shipped_caps_doc():
    for path in _FIVE_DOCS:
        assert path.exists(), f"missing doc: {path}"
        text = (skill_text.read_skill_text("tp-run-full-design")
                if path == _SKILLS / "tp-run-full-design" / "SKILL.md" else path.read_text(encoding="utf-8"))
        assert "file-size-caps.md" in text, (
            f"{path.relative_to(_REPO_ROOT)} must cite file-size-caps.md"
        )


def test_commit_time_docs_name_the_shipped_runner():
    for path in _COMMIT_GUARD_DOCS:
        assert path.exists(), f"missing doc: {path}"
        text = path.read_text(encoding="utf-8")
        has_commit_guard = "commit_guard.py" in text
        has_hot_patch = path in _HOT_PATCH_OK and "hot_patch_check.py" in text
        assert has_commit_guard or has_hot_patch, (
            f"{path.relative_to(_REPO_ROOT)} must name commit_guard.py"
            + (" (or hot_patch_check.py)" if path in _HOT_PATCH_OK else "")
        )


def test_cwd_preflight_no_longer_cites_28():
    text = (_SHARED / "cwd_preflight.py").read_text(encoding="utf-8")
    assert "#28" not in text, "cwd_preflight.py must not cite the retired #28"
