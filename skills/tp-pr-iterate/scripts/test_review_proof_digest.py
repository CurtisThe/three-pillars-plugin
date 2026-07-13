"""Tests for review_proof.py — Phase 1 (Tasks 1.4–1.5) + Task 5.1.

Split out of test_review_proof.py (file-size cap, CLAUDE.md §File Size Limits) —
Tasks 1.1–1.3 (numstat/capture/present) stay there; this file covers:
    Task 1.4  empty_diff_sentinel + format_proof_digest
    Task 1.5  file-size + import-cleanliness guard
    Task 5.1  gitignore review-proof carve (git check-ignore assertion)
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import review_proof  # noqa: E402
import review_merge  # noqa: E402


# ============================================================
# Task 1.4 — empty_diff_sentinel + format_proof_digest
# ============================================================


def test_empty_diff_sentinel_is_degraded_review():
    """is_degraded_review([empty_diff_sentinel()]) must be True."""
    sentinel = review_proof.empty_diff_sentinel()
    assert review_merge.is_degraded_review([sentinel]) is True


def test_empty_diff_sentinel_has_empty_diff_source():
    """Sentinel source is 'empty-diff' and file matches _unparseable_finding shape."""
    sentinel = review_proof.empty_diff_sentinel()
    assert sentinel.get("source") == "empty-diff"
    assert "<review-output:empty-diff>" in sentinel.get("file", "")


def test_format_proof_digest_non_degraded():
    """Non-degraded meta renders base short SHA, FULL head SHA + file stats.

    The head is emitted FULL, never truncated (round-2 finding): the
    detector's currency compare is exact-match, and a 7-char head would make
    proof grindable via SHA-prefix collision (lucky-commit-class tooling)."""
    meta = {
        "base": "abc1234567",
        "head": "def5678901",
        "files_changed": 7,
        "insertions": 123,
        "deletions": 45,
        "degraded": False,
        "reason": None,
    }
    digest = review_proof.format_proof_digest(meta)
    assert "abc1234" in digest
    assert "`def5678901`" in digest  # FULL head, backtick-delimited
    assert "`def5678`" not in digest  # never the truncated 7-char form
    assert "7 files" in digest
    assert "+123" in digest
    assert "−45" in digest
    assert digest.startswith("<sub>")
    assert digest.endswith("</sub>")


def test_format_proof_digest_with_angles():
    """Angles clause appears when angle_finding_counts provided."""
    meta = {
        "base": "abc", "head": "def",
        "files_changed": 3, "insertions": 10, "deletions": 2,
        "degraded": False, "reason": None,
    }
    digest = review_proof.format_proof_digest(meta, [("correctness", 2), ("edge", 0)])
    assert "angles [correctness:2, edge:0]" in digest


def test_format_proof_digest_without_angles_no_clause():
    """Angles clause is omitted when angle_finding_counts is None or empty."""
    meta = {
        "base": "a", "head": "b",
        "files_changed": 1, "insertions": 5, "deletions": 0,
        "degraded": False, "reason": None,
    }
    digest = review_proof.format_proof_digest(meta, None)
    assert "angles" not in digest

    digest2 = review_proof.format_proof_digest(meta, [])
    assert "angles" not in digest2


def test_format_proof_digest_degraded():
    """Degraded meta → ⚠️ DEGRADED clause."""
    meta = {"degraded": True, "reason": "empty-diff"}
    digest = review_proof.format_proof_digest(meta)
    assert "DEGRADED" in digest
    assert "empty-diff" in digest
    assert "refused convergence" in digest


def test_format_proof_digest_single_line(tmp_path):
    """Digest is a single line (no newlines, no transcripts)."""
    meta = {
        "base": "a", "head": "b",
        "files_changed": 1, "insertions": 1, "deletions": 0,
        "degraded": False, "reason": None,
    }
    digest = review_proof.format_proof_digest(meta, [("t", 1)])
    assert "\n" not in digest


# ============================================================
# Task 1.5 — file-size + import-cleanliness guard
# ============================================================


def test_review_proof_under_cap():
    """review_proof.py is ≤500 lines AND ≤50000 chars (no grandfather)."""
    src_path = HERE / "review_proof.py"
    src = src_path.read_text(encoding="utf-8")
    lines = src.count("\n") + 1
    chars = len(src)
    assert lines <= 500, f"review_proof.py is {lines} lines (cap=500)"
    assert chars <= 50000, f"review_proof.py is {chars} chars (cap=50000)"


def test_review_proof_c1_clean():
    """review_proof.py contains no import anthropic / from anthropic / claude_agent."""
    src = (HERE / "review_proof.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "anthropic" not in (alias.name or "").lower(), (
                    f"review_proof.py must not import anthropic (C1); found: {alias.name}"
                )
                assert "claude_agent" not in (alias.name or "").lower(), (
                    f"review_proof.py must not import claude_agent (C1); found: {alias.name}"
                )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert "anthropic" not in module.lower(), (
                f"review_proof.py does `from {module} import …` — violates C1"
            )
            assert "claude_agent" not in module.lower(), (
                f"review_proof.py does `from {module} import …` — violates C1"
            )


# ============================================================
# Task 5.1 — gitignore review-proof carve
# ============================================================


def test_gitignore_ignores_review_proof():
    """Shipped .gitignore must contain the .three-pillars/review-proof/ pattern
    on its own line, with the comment on its own separate line above it.
    """
    # Find the project root
    from project_root import find_project_root
    repo_root = find_project_root(HERE)
    assert repo_root is not None, "Could not find git root from test file"
    gitignore = repo_root / ".gitignore"
    assert gitignore.exists(), f".gitignore not found at {gitignore}"
    text = gitignore.read_text(encoding="utf-8")
    lines = text.splitlines()
    # Pattern must appear as its own line
    assert ".three-pillars/review-proof/" in lines, (
        "'.three-pillars/review-proof/' must appear as a standalone line in .gitignore"
    )
    # The comment must be on its own line (not inline)
    for line in lines:
        stripped = line.strip()
        if ".three-pillars/review-proof/" in stripped and stripped.startswith("#"):
            pytest.fail(
                "The .gitignore comment for review-proof must be on its OWN line, "
                "not the same line as the pattern"
            )
    # Verify a comment line about review-proof appears above the pattern
    pattern_idx = lines.index(".three-pillars/review-proof/")
    comment_above = any(
        l.startswith("#") and "review-proof" in l.lower()
        for l in lines[max(0, pattern_idx - 5):pattern_idx]
    )
    assert comment_above, (
        "A comment mentioning 'review-proof' must appear on its own line above the pattern"
    )


def test_gitignore_check_ignore(tmp_path):
    """git check-ignore must match a path under .three-pillars/review-proof/."""
    import subprocess
    from project_root import find_project_root
    repo_root = find_project_root(HERE)
    assert repo_root is not None
    test_path = ".three-pillars/review-proof/abc123/meta.json"
    result = subprocess.run(
        ["git", "check-ignore", "-q", test_path],
        cwd=str(repo_root),
        capture_output=True,
    )
    assert result.returncode == 0, (
        f"git check-ignore did not match {test_path!r} — "
        f"is '.three-pillars/review-proof/' in .gitignore?"
    )
