"""Tests for find_project_root — project root resolution via git rev-parse.

Tests use real git operations in tmp directories (suite convention: no mocks).
"""
import os
import subprocess
from pathlib import Path

import pytest


def _init_repo(path: Path) -> None:
    """Initialize a minimal git repo at path with one commit."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test.com"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"],
        check=True, capture_output=True,
    )
    # Need at least one commit for HEAD to exist
    sentinel = path / "README"
    sentinel.write_text("init")
    subprocess.run(
        ["git", "-C", str(path), "add", "README"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init"],
        check=True, capture_output=True,
    )


def test_repo_root_resolved(tmp_path):
    """find_project_root(repo_path) returns the resolved toplevel Path."""
    from project_root import find_project_root

    repo = tmp_path / "myrepo"
    _init_repo(repo)

    result = find_project_root(start=repo)
    assert result is not None
    assert result == repo.resolve()


def test_nested_cwd_same_toplevel(tmp_path):
    """Starting from a nested subdir returns the same toplevel."""
    from project_root import find_project_root

    repo = tmp_path / "myrepo"
    _init_repo(repo)

    nested = repo / "a" / "b" / "c"
    nested.mkdir(parents=True)

    result = find_project_root(start=nested)
    assert result is not None
    assert result == repo.resolve()


def test_non_repo_returns_none(tmp_path):
    """A non-git directory returns None."""
    from project_root import find_project_root

    non_repo = tmp_path / "not_a_repo"
    non_repo.mkdir()

    result = find_project_root(start=non_repo)
    assert result is None


def test_default_start_uses_cwd(tmp_path, monkeypatch):
    """start=None uses cwd (monkeypatched into a tmp repo)."""
    from project_root import find_project_root

    repo = tmp_path / "myrepo"
    _init_repo(repo)

    monkeypatch.chdir(repo)
    result = find_project_root()
    assert result is not None
    assert result == repo.resolve()
