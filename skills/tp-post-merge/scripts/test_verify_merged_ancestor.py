"""Tests for verify_merged.ancestor_status (review-log-survives-teardown 1.1).

A branch tip counts as merged only when it is an ancestor of the base ref AND
sits off the base's first-parent line (i.e. a real --no-ff merge commit, not a
fast-forward or an empty branch). Real tmp_path git repos (bare origin +
clone); GIT_* scrubbed, identity set; no network.

Run with: pytest skills/tp-post-merge/scripts/test_verify_merged_ancestor.py -q
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from verify_merged import ancestor_status  # noqa: E402

_CLEAN = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
_CLEAN.update({"GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@test",
               "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@test"})


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=str(cwd), check=True, env=_CLEAN,
                       capture_output=True, text=True)
    return r.stdout.strip()


def _commit(repo: Path, name: str) -> None:
    (repo / name).write_text(name)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name)


@pytest.fixture
def repo(tmp_path) -> Path:
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _git(origin, "init", "-q", "--bare", "-b", "master")
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", str(origin), str(clone))
    _git(clone, "checkout", "-q", "-B", "master")
    _commit(clone, "base.txt")
    _git(clone, "push", "-q", "origin", "master")
    _git(clone, "branch", "tp/demo")
    return clone


def _work(repo: Path, name: str) -> None:
    _git(repo, "checkout", "-q", "tp/demo")
    _commit(repo, name)
    _git(repo, "checkout", "-q", "master")


def test_no_ff_merge_is_merged(repo):
    _work(repo, "a.txt")
    tip = _git(repo, "rev-parse", "tp/demo")
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge", "tp/demo")
    _git(repo, "push", "-q", "origin", "master")
    ok, reason = ancestor_status(str(repo), "demo", "master")
    assert ok is True
    assert tip[:7] in reason


def test_branch_with_no_commits_is_refused(repo):
    ok, reason = ancestor_status(str(repo), "demo", "master")
    assert ok is False
    assert "first-parent" in reason


def test_fast_forward_merge_is_refused(repo):
    _work(repo, "a.txt")
    _git(repo, "merge", "-q", "--ff-only", "tp/demo")
    _git(repo, "push", "-q", "origin", "master")
    ok, reason = ancestor_status(str(repo), "demo", "master")
    assert ok is False
    assert "first-parent" in reason


def test_unmerged_branch_is_refused(repo):
    _work(repo, "a.txt")
    ok, reason = ancestor_status(str(repo), "demo", "master")
    assert ok is False
    assert "not in" in reason
    assert "first-parent" not in reason


def test_missing_ref_is_refused(repo):
    _git(repo, "branch", "-D", "tp/demo")
    ok, reason = ancestor_status(str(repo), "demo", "master")
    assert ok is False
    assert "tp/demo" in reason


def test_origin_ref_used_when_local_branch_deleted(repo):
    _work(repo, "a.txt")
    _git(repo, "push", "-q", "origin", "tp/demo")
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge", "tp/demo")
    _git(repo, "push", "-q", "origin", "master")
    _git(repo, "branch", "-D", "tp/demo")
    ok, _ = ancestor_status(str(repo), "demo", "master")
    assert ok is True


def test_never_raises_outside_a_repo(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    ok, reason = ancestor_status(str(plain), "demo", "master")
    assert ok is False
    assert isinstance(reason, str) and reason


def test_local_and_origin_tips_differ_requires_both(repo):
    _work(repo, "a.txt")
    _git(repo, "push", "-q", "origin", "tp/demo")
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge", "tp/demo")
    _git(repo, "push", "-q", "origin", "master")
    _work(repo, "b.txt")  # local-only commit
    local_tip = _git(repo, "rev-parse", "tp/demo")
    ok, reason = ancestor_status(str(repo), "demo", "master")
    assert ok is False
    assert local_tip[:7] in reason
    _git(repo, "push", "-q", "origin", "tp/demo")
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge2", "tp/demo")
    _git(repo, "push", "-q", "origin", "master")
    ok, _ = ancestor_status(str(repo), "demo", "master")
    assert ok is True
