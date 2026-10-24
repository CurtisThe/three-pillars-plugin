"""Scratch checkouts leave a run's in-tree TMPDIR (review r1, PR #391; design: run-scratch-in-fence).

A design run's TMPDIR is `<worktree>/.tp-scratch/run`. A scratch worktree or clone made under it
sits inside the run's checkout, so a pytest run there takes the checkout's ini as its rootdir and
every judged node reads `unverified`. Both shipped makers put their parent in
`run_scratch.outside_tmpdir()` instead (patched here to a dir under tmp_path).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

import changed_tests_runs as ctr
import refactor_invariance as rv
import run_scratch
import task_scope

IDENTITY = {"GIT_AUTHOR_NAME": "f", "GIT_AUTHOR_EMAIL": "f@t",
            "GIT_COMMITTER_NAME": "f", "GIT_COMMITTER_EMAIL": "f@t"}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    sysdir = tmp_path / "systmp"
    sysdir.mkdir()
    monkeypatch.setattr(run_scratch, "_SYSTEM_TMP", str(sysdir))
    monkeypatch.setenv("TMPDIR", str(tmp_path / "wt" / ".tp-scratch" / "run"))
    r = tmp_path / "r"
    r.mkdir()
    env = task_scope._git_env(**IDENTITY)
    for args in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "x"]):
        subprocess.run(["git", "-C", str(r), *args], check=True, capture_output=True, env=env)
    sha = subprocess.run(["git", "-C", str(r), "rev-parse", "HEAD"], check=True,
                         capture_output=True, text=True, env=env).stdout.strip()
    return r, sha, sysdir


def test_refactor_invariance_scratch_worktree_is_outside(repo):
    r, _sha, sysdir = repo
    with rv._scratch(r) as path:
        assert Path(path).parent.parent == sysdir and os.path.isdir(path)
    assert os.listdir(sysdir) == []


def test_changed_tests_runs_clone_is_outside(repo):
    r, sha, sysdir = repo
    with ctr._detached(r, sha) as path:
        assert Path(path).parent.parent == sysdir and os.path.isdir(path)
    assert os.listdir(sysdir) == []
