"""test_trace_wiring.py — Wiring tests for Phase 6 (Tasks 6.1, 6.2, 6.3).

Tests that verify the integration plumbing — gitignore entry, companion doc,
and SKILL.md pointer — read from the SHIPPED files via git rev-parse so they
test actual committed content, not in-memory copies.
"""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helper: repo root from git
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    """Return the repo root by asking git (works from any worktree)."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(result.stdout.strip())


# ---------------------------------------------------------------------------
# Task 6.1: .trace/ gitignore entry
# ---------------------------------------------------------------------------


class TestTraceGitignored:
    """Task 6.1 — .gitignore contains the trace dir pattern."""

    def test_trace_dir_gitignored(self):
        """The .gitignore line 'three-pillars-docs/tp-designs/*/.trace/' must exist."""
        root = _repo_root()
        gitignore_path = root / ".gitignore"
        assert gitignore_path.exists(), ".gitignore not found at repo root"

        lines = gitignore_path.read_text(encoding="utf-8").splitlines()
        expected = "three-pillars-docs/tp-designs/*/.trace/"
        assert expected in lines, (
            f"{expected!r} not found in .gitignore; "
            f"run: echo '{expected}' >> .gitignore"
        )

    def test_sample_trace_path_matches_gitignore_pattern(self):
        """A sample .trace/<run-id>/ path is covered by the gitignore glob."""
        # The gitignore line uses a wildcard for the design slug; verify the
        # pattern semantics match a representative path using fnmatch.
        pattern = "three-pillars-docs/tp-designs/*/.trace/"
        sample_path = "three-pillars-docs/tp-designs/my-design/.trace/"
        assert fnmatch.fnmatch(sample_path, pattern), (
            f"fnmatch({sample_path!r}, {pattern!r}) is False — pattern mismatch"
        )

    def test_git_check_ignore_flags_trace_path(self):
        """git check-ignore confirms a sample .trace/ path is ignored."""
        root = _repo_root()
        # Use a path relative to repo root
        sample = "three-pillars-docs/tp-designs/my-design/.trace/01J9ABCDEF123456789ABCDEFG/"
        result = subprocess.run(
            ["git", "check-ignore", "-v", sample],
            capture_output=True,
            text=True,
            cwd=str(root),
        )
        # exit 0 means the path is ignored; non-zero means it's not
        assert result.returncode == 0, (
            f"git check-ignore returned {result.returncode} for {sample!r}; "
            f"stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# Task 6.2: Companion doc coherence
# ---------------------------------------------------------------------------

_COMPANION_REQUIRED_SECTIONS = [
    # (section-id, at-least-one-of these substrings must appear)
    "record hook site",
    "replay re-drive",
    "cache-miss",
    "canary",
]


class TestCompanionDocCoherence:
    """Task 6.2 — record-replay.md exists, ≤500 lines, covers 4 required sections."""

    def _companion_path(self) -> Path:
        root = _repo_root()
        return root / "skills" / "tp-run-full-design" / "record-replay.md"

    def test_companion_doc_exists(self):
        path = self._companion_path()
        assert path.exists(), (
            f"record-replay.md not found at {path}; Task 6.2 not yet implemented"
        )

    def test_companion_doc_line_count(self):
        """record-replay.md must not exceed 500 lines (hard cap, no grandfather)."""
        path = self._companion_path()
        if not path.exists():
            pytest.skip("record-replay.md not yet created")
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) <= 500, (
            f"record-replay.md has {len(lines)} lines — exceeds 500-line hard cap"
        )

    def test_companion_doc_coherence(self):
        """record-replay.md covers all 4 required sections (case-insensitive grep)."""
        path = self._companion_path()
        if not path.exists():
            pytest.skip("record-replay.md not yet created")
        text = path.read_text(encoding="utf-8").lower()
        missing = []
        for section in _COMPANION_REQUIRED_SECTIONS:
            if section.lower() not in text:
                missing.append(section)
        assert not missing, (
            f"record-replay.md is missing required sections: {missing!r}"
        )


# ---------------------------------------------------------------------------
# Task 6.3: SKILL.md pointer line
# ---------------------------------------------------------------------------


class TestSkillPointer:
    """Task 6.3 — SKILL.md has exactly one pointer to record-replay.md, ≤1081 lines."""

    def _skill_path(self) -> Path:
        root = _repo_root()
        return root / "skills" / "tp-run-full-design" / "SKILL.md"

    def test_skill_pointer(self):
        """SKILL.md has exactly one reference to record-replay.md AND ≤1081 lines."""
        path = self._skill_path()
        assert path.exists(), f"SKILL.md not found at {path}"
        lines = path.read_text(encoding="utf-8").splitlines()

        # Absolute line-count cap
        assert len(lines) <= 1081, (
            f"SKILL.md has {len(lines)} lines — exceeds 1081-line cap "
            f"(grandfathered at 1079 + ≤2 pointer lines)"
        )

        # Exactly one pointer to record-replay.md
        pointer_lines = [ln for ln in lines if "record-replay.md" in ln]
        assert len(pointer_lines) == 1, (
            f"Expected exactly 1 line in SKILL.md referencing record-replay.md, "
            f"found {len(pointer_lines)}: {pointer_lines!r}"
        )

    def test_skill_pointer_near_return_clipping(self):
        """The record-replay.md pointer lives near the ## Return clipping section."""
        path = self._skill_path()
        if not path.exists():
            pytest.skip("SKILL.md not found")
        lines = path.read_text(encoding="utf-8").splitlines()

        # Find the '## Return clipping' heading (must start with '##')
        clipping_idx = next(
            (i for i, ln in enumerate(lines) if ln.strip().startswith("## Return clipping")),
            None,
        )
        pointer_idx = next(
            (i for i, ln in enumerate(lines) if "record-replay.md" in ln),
            None,
        )
        if clipping_idx is None or pointer_idx is None:
            pytest.skip("Cannot locate anchors in SKILL.md")

        # Pointer should appear within 20 lines of ## Return clipping
        distance = abs(pointer_idx - clipping_idx)
        assert distance <= 20, (
            f"record-replay.md pointer is {distance} lines from ## Return clipping "
            f"(expected within 20 lines)"
        )
