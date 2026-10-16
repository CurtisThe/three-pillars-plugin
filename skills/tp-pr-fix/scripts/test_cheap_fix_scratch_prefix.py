"""Tests for cheap_fix.scratch's owner `prefix` — the review-prep scratch reuses the
pr-fix worktree helper under its own owner prefix (`review-prep-*`), while the default
stays `cheap-fix-*` and `_is_owner` / `discard` accept both.

design: cheap-tier-review-prep (Task 5.1). A tmp git repo with `.tp-scratch/`
gitignored stands in for the review-prep seat's checkout (path moved by launch-role-precedence
Task 3.7).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cheap_fix  # noqa: E402


def _git(cwd, *args) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    (root / "a.py").write_text("a", encoding="utf-8")
    (root / ".gitignore").write_text("/.tp-scratch/\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


def _head(repo) -> str:
    return _git(repo, "rev-parse", "HEAD")


def _gone(repo, path: Path) -> bool:
    return not path.exists() and str(path) not in _git(repo, "worktree", "list", "--porcelain")


# --- scratch with a prefix -------------------------------------------------------------


def test_default_prefix_still_cheap_fix(repo):
    path = cheap_fix.scratch(repo, _head(repo))
    try:
        owner = path.resolve().parent
        assert owner.parent == (repo / ".tp-scratch").resolve()
        assert owner.name.startswith("cheap-fix-")
        assert path.name == "r1"
    finally:
        cheap_fix.discard(path)


def test_review_prep_prefix_makes_a_review_prep_owner(repo):
    path = cheap_fix.scratch(repo, _head(repo), prefix="review-prep")
    try:
        owner = path.resolve().parent
        assert owner.parent == (repo / ".tp-scratch").resolve()
        assert owner.name.startswith("review-prep-")
        assert path.name == "r1"
        assert _git(path, "rev-parse", "HEAD") == _head(repo)
        assert str(path) in _git(repo, "worktree", "list", "--porcelain")
    finally:
        cheap_fix.discard(path)
    assert _gone(repo, path)


# --- _is_owner accepts both prefixes ----------------------------------------------------


def test_is_owner_accepts_both_prefixes_and_refuses_others(repo):
    base = repo / ".tp-scratch"
    base.mkdir(parents=True, exist_ok=True)
    good = [base / "cheap-fix-abc", base / "review-prep-xyz"]
    for d in good:
        d.mkdir(exist_ok=True)
        assert cheap_fix._is_owner(d) is True
    other = base / "other-xyz"
    other.mkdir()
    assert cheap_fix._is_owner(other) is False
    # a symlink named like an owner is not an owner
    link = base / "review-prep-link"
    link.symlink_to(good[1])
    try:
        assert cheap_fix._is_owner(link) is False
    finally:
        link.unlink()
        for d in good:
            d.rmdir()
        other.rmdir()


# --- discard removes a review-prep scratch ----------------------------------------------


def test_discard_removes_a_review_prep_scratch(repo):
    path = cheap_fix.scratch(repo, _head(repo), prefix="review-prep")
    owner = path.parent
    cheap_fix.discard(path)
    assert _gone(repo, path)
    assert not owner.exists()
    assert _git(repo, "status", "--porcelain") == ""
