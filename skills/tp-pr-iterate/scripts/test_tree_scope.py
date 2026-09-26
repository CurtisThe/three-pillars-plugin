"""Tests for tree_scope — the loop-excluded pathspecs and the fix-paths check.

design: iterate-convergence-budget (Task 5.1, Q1)

The loop's own bookkeeping (`three-pillars-docs/**`, `.three-pillars/config.json`)
never counts as dirty tracked code and never lands in a fix commit's paths.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import tree_scope  # noqa: E402
from tree_scope import check_fix_paths, derive_fix_paths, tracked_dirty, untracked_snapshot  # noqa: E402

_GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_NOSYSTEM": "1", "HOME": "/nonexistent"}


def _git(repo, *args):
    env = {**os.environ, **_GIT_ENV}
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                         env=env, check=True)
    return out.stdout.strip()


def _write(repo, rel, text="x\n"):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _write(r, ".three-pillars/config.json", "{}\n")
    _write(r, "three-pillars-docs/x.md", "doc\n")
    _write(r, "src/a.py", "a = 1\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "base")
    return r


def test_loop_excludes_are_the_q1_pathspecs():
    assert tree_scope.LOOP_EXCLUDES == (":(exclude)three-pillars-docs",
                                        ":(exclude).three-pillars/config.json")


def test_config_edit_is_clean(repo):
    """[Q1] a raised limit in the REAL config does not make the tree dirty."""
    assert tracked_dirty(repo) is False
    _write(repo, ".three-pillars/config.json", '{"pdw": {"guards": {"round_cap": 7}}}\n')
    assert tracked_dirty(repo) is False
    _write(repo, "three-pillars-docs/x.md", "doc edited\n")
    assert tracked_dirty(repo) is False
    _write(repo, "stray.txt", "untracked\n")
    assert tracked_dirty(repo) is False
    _write(repo, "src/a.py", "a = 2\n")
    assert tracked_dirty(repo) is True


def test_tracked_dirty_sees_staged_code(repo):
    _write(repo, "src/a.py", "a = 3\n")
    _git(repo, "add", "src/a.py")
    assert tracked_dirty(repo) is True


def test_derive_fix_paths_excludes_config(repo):
    """[Q1] the derived paths are code only, never the loop's bookkeeping."""
    _write(repo, "pre_existing.txt", "stray before the edit\n")
    before = untracked_snapshot(repo)
    assert before == {"pre_existing.txt"}
    _write(repo, "src/a.py", "a = 2\n")
    _write(repo, "src/b.py", "b = 1\n")
    _write(repo, ".three-pillars/config.json", '{"x": 1}\n')
    _write(repo, "three-pillars-docs/x.md", "doc edited\n")
    _write(repo, "three-pillars-docs/new.md", "new doc\n")
    assert derive_fix_paths(repo, before) == ["src/a.py", "src/b.py"]


def test_derive_fix_paths_clean_tree_is_empty(repo):
    assert derive_fix_paths(repo, untracked_snapshot(repo)) == []


def test_git_failure_raises(tmp_path):
    with pytest.raises(tree_scope.TreeScopeError):
        tracked_dirty(tmp_path / "missing")


# ---------- check_fix_paths (pure, no git) ----------


def test_check_fix_paths_equal_sets_ok():
    assert check_fix_paths(["src/a.py", "src/b.py"], ["src/b.py", "src/a.py"]) == "ok"


def test_check_fix_paths_stray_extra_mismatch():
    assert check_fix_paths(["src/a.py", "stray.py"], ["src/a.py"]) == "fix-paths-mismatch"


def test_check_fix_paths_missing_claimed_mismatch():
    assert check_fix_paths(["src/a.py"], ["src/a.py", "src/b.py"]) == "fix-paths-mismatch"


def test_check_fix_paths_empty_derived_mismatch():
    assert check_fix_paths([], ["src/a.py"]) == "fix-paths-mismatch"
