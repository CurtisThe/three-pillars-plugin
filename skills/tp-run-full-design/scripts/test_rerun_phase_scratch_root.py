"""Tier 3.5 rerun scratch lives under the `-wt` root, never under a `.claude/` dir.

design: worktrees-under-wt-only (Task 2.1). Real tmp repos via `rerun_fixture`.
"""
from __future__ import annotations

import os

import pytest

import rerun_fixture as fx
import rerun_phase_tests as rpt
import wt_root

SLUG = "demo"


def _seat(tmp_path):
    repo, sha = fx.make_repo(tmp_path)
    return repo, sha


def _wt(tmp_path):
    repo, sha = fx.make_repo(tmp_path)
    wt = tmp_path / "x-wt" / SLUG
    wt.parent.mkdir()
    fx.git(repo, "worktree", "add", "-q", "-b", f"tp/{SLUG}", str(wt), sha)
    return wt, sha


@pytest.mark.parametrize("make", [_seat, _wt])
def test_scratch_parent_is_wt_root_and_removed_clean(tmp_path, make):
    repo, sha = make(tmp_path)
    path, branch = rpt._add_scratch(repo, sha, SLUG)
    try:
        assert os.path.realpath(path.parent) == os.path.realpath(wt_root.scratch_parent(repo, SLUG))
        assert ".claude" not in path.parts
        assert path.name.startswith("tp-rerun-")
        assert branch.startswith(f"tp-rerun/{SLUG}-")
        assert path.is_dir()
    finally:
        rpt._remove_scratch(repo, path, branch)
    assert not path.exists()
    assert fx.git(repo, "branch", "--list", "tp-rerun/*") == ""
    assert str(path) not in fx.git(repo, "worktree", "list", "--porcelain")
