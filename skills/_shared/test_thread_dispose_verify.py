"""Tests for thread_dispose_verify.py — verify-before-dispose guard (T1.2).

Regression-pins the stale-re-flag case (project_copilot_stale_reflag_disposition):
  A finding re-anchored onto a region that current code has already fixed must:
  - be disposed as stale/addressed (honest reply + resolve)
  - never trigger code modification (read-only guard; no write/edit/gh mutation
    beyond reply + resolve)

The guard is read-only: it may read files from disk but NEVER modifies any file.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import thread_dispose_verify  # noqa: E402


# ---------- helpers ----------


def _make_finding(path: str, pattern: str, comment_id: int = 1) -> dict:
    """Build a minimal finding dict with path + body (pattern is derived from body)."""
    return {
        "comment_id": comment_id,
        "thread_id": f"RT_{comment_id}",
        "path": path,
        "body": f"Consider fixing the pattern: `{pattern}` in this file.",
    }


# ---------- pattern_still_present ----------


def test_pattern_present_returns_true(tmp_path):
    """If the flagged pattern still exists in the file, returns True."""
    src = tmp_path / "foo.py"
    src.write_text("x = eval(user_input)  # bad\n")
    finding = _make_finding("foo.py", "eval(user_input)")
    result = thread_dispose_verify.pattern_still_present(finding, base_dir=tmp_path)
    assert result is True


def test_pattern_absent_returns_false(tmp_path):
    """If the flagged pattern has been removed, returns False (already fixed)."""
    src = tmp_path / "foo.py"
    src.write_text("x = safe_call(user_input)  # fixed\n")
    finding = _make_finding("foo.py", "eval(user_input)")
    result = thread_dispose_verify.pattern_still_present(finding, base_dir=tmp_path)
    assert result is False


def test_missing_file_returns_none(tmp_path):
    """If the file at path does not exist, returns None (cannot verify)."""
    finding = _make_finding("nonexistent.py", "eval")
    result = thread_dispose_verify.pattern_still_present(finding, base_dir=tmp_path)
    assert result is None


def test_empty_path_returns_none(tmp_path):
    """If the finding has no path, returns None."""
    finding = {"comment_id": 1, "thread_id": "RT_1", "path": None, "body": "some body"}
    result = thread_dispose_verify.pattern_still_present(finding, base_dir=tmp_path)
    assert result is None


# ---------- stale re-flag: already-fixed disposition ----------


def test_stale_reflag_disposes_as_stale_addressed(tmp_path):
    """Core regression: an already-fixed finding is classified stale_addressed."""
    # File has already been fixed — pattern no longer present
    src = tmp_path / "bar.py"
    src.write_text("x = safe_parse(data)  # fix landed\n")
    finding = _make_finding("bar.py", "eval(data)")
    verdict = thread_dispose_verify.check_before_dispose(finding, base_dir=tmp_path)
    assert verdict == "stale_addressed", (
        f"already-fixed region must be classified stale_addressed; got {verdict!r}"
    )


def test_still_flagged_returns_normal(tmp_path):
    """A finding whose pattern still exists returns 'normal' (standard disposition)."""
    src = tmp_path / "bar.py"
    src.write_text("x = eval(data)  # still bad\n")
    finding = _make_finding("bar.py", "eval(data)")
    verdict = thread_dispose_verify.check_before_dispose(finding, base_dir=tmp_path)
    assert verdict == "normal", (
        f"finding still present must be classified normal; got {verdict!r}"
    )


def test_unverifiable_returns_normal(tmp_path):
    """File missing / unverifiable → 'normal' (conservative: proceed with disposition_for)."""
    finding = _make_finding("missing.py", "some_pattern")
    verdict = thread_dispose_verify.check_before_dispose(finding, base_dir=tmp_path)
    assert verdict == "normal", (
        "unverifiable path must fall back to normal (conservative)"
    )


# ---------- no code mutation (read-only guard) ----------


def test_guard_does_not_write_any_file(tmp_path):
    """The guard is strictly read-only — no files created or modified."""
    src = tmp_path / "baz.py"
    content = "x = eval(y)  # still here\n"
    src.write_text(content)

    before_mtime = src.stat().st_mtime
    before_files = set(tmp_path.iterdir())

    finding = _make_finding("baz.py", "eval(y)")
    thread_dispose_verify.check_before_dispose(finding, base_dir=tmp_path)

    after_mtime = src.stat().st_mtime
    after_files = set(tmp_path.iterdir())

    assert after_mtime == before_mtime, "guard must not modify any existing file"
    assert after_files == before_files, "guard must not create new files"


def test_stale_guard_does_not_write_any_file(tmp_path):
    """Even for stale_addressed verdict, the guard creates or modifies no files."""
    src = tmp_path / "baz.py"
    content = "x = safe(y)  # fixed\n"
    src.write_text(content)

    before_mtime = src.stat().st_mtime
    before_files = set(tmp_path.iterdir())

    finding = _make_finding("baz.py", "eval(y)")
    thread_dispose_verify.check_before_dispose(finding, base_dir=tmp_path)

    after_mtime = src.stat().st_mtime
    after_files = set(tmp_path.iterdir())

    assert after_mtime == before_mtime, "stale_addressed guard must not modify any file"
    assert after_files == before_files, "stale_addressed guard must not create new files"
