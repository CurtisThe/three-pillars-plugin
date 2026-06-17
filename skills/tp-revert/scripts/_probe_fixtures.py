"""Fixtures and helpers shared by tp-revert probe tests.

The merge_repo fixture lives here (not in conftest.py) so that test files can
import it by name directly, avoiding the conftest name-collision when running
combined test suites (skills/_shared/ + skills/tp-revert/scripts/ together).
Import pattern in test files:
    from _probe_fixtures import merge_repo  # noqa: F401
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import NamedTuple

import pytest


class MergeRepo(NamedTuple):
    origin: Path
    clone: Path


def _g(cwd, *a):
    return subprocess.run(["git"] + list(a), cwd=cwd,
                          capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture()
def merge_repo(tmp_path: Path) -> MergeRepo:
    """Bare origin + working clone with git identity configured."""
    origin, clone = tmp_path / "origin.git", tmp_path / "clone"
    origin.mkdir()
    clone.mkdir()
    subprocess.run(["git", "init", "-b", "master", "--bare", str(origin)], check=True,
                   capture_output=True)
    subprocess.run(["git", "init", "-b", "master", str(clone)], check=True,
                   capture_output=True)
    for k, v in [("user.email", "t@t.com"), ("user.name", "T")]:
        _g(clone, "config", k, v)
    _g(clone, "remote", "add", "origin", str(origin))
    (clone / "README.md").write_text("init\n")
    _g(clone, "add", "README.md")
    _g(clone, "commit", "-m", "init")
    _g(clone, "push", "-u", "origin", "master")
    _g(clone, "fetch", "origin")
    return MergeRepo(origin=origin, clone=clone)


def land_merge(repo: MergeRepo, branch: str, files: dict[str, str]) -> str:
    """Land a true no-ff merge commit on master. Returns merge_sha."""
    c = repo.clone
    _g(c, "checkout", "master")
    _g(c, "checkout", "-b", branch)
    for f, v in files.items():
        (c / f).write_text(v)
        _g(c, "add", f)
    _g(c, "commit", "-m", f"feat: {branch}")
    _g(c, "checkout", "master")
    _g(c, "merge", "--no-ff", branch, "-m", f"Merge branch '{branch}'")
    sha = _g(c, "rev-parse", "HEAD")
    _g(c, "push", "origin", "master")
    return sha


def first_parent_commit(repo: MergeRepo, files: dict[str, str]) -> str:
    """Add a plain first-parent commit on master. Returns sha."""
    c = repo.clone
    _g(c, "checkout", "master")
    for f, v in files.items():
        (c / f).write_text(v)
        _g(c, "add", f)
    _g(c, "commit", "-m", "chore: first-parent")
    _g(c, "push", "origin", "master")
    return _g(c, "rev-parse", "HEAD")


def make_gh_fn(response: dict):
    """Fake gh_fn that returns JSON-encoded response with returncode=0."""
    class R:
        stdout = json.dumps(response)
        returncode = 0
    return lambda cmd, **kw: R()
