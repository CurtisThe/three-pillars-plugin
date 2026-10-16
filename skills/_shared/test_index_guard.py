"""Tests for index_guard: a stale index after HEAD moves must be refused, never committed."""
import subprocess
from pathlib import Path

import pytest

import index_guard

pytestmark = pytest.mark.skipif(
    subprocess.run(["git", "--version"], capture_output=True).returncode != 0, reason="git missing"
)


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def repo(tmp_path):
    """Two commits: A (skipif test) then B (the review fix: refusal + a new test)."""
    git(tmp_path, "init", "-q", "-b", "work")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "t")
    git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / "test_a.py").write_text("@skipif\ndef test_a(): pass\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "A")
    (tmp_path / "test_a.py").write_text("def test_a(): refuse()\n", encoding="utf-8")
    (tmp_path / "test_b.py").write_text("def test_b(): pass\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "B: review fix")
    return tmp_path


def stale(repo):
    """Index back at A while HEAD is B: staging the exact revert of the review fix."""
    git(repo, "read-tree", "HEAD~1")


def test_clean_index_passes(repo):
    assert index_guard.is_clean(repo)
    assert index_guard.main(["-C", str(repo), "check"]) == 0


def test_stale_revert_of_tip_is_refused(repo, capsys):
    stale(repo)
    assert not index_guard.is_clean(repo)
    assert index_guard.main(["-C", str(repo), "check"]) == 1
    out = capsys.readouterr().out
    assert "STALE INDEX" in out and "test_b.py" in out and "test_a.py" in out


def test_head_moved_forward_under_populated_index_is_refused(repo):
    git(repo, "checkout", "-q", "-b", "side", "HEAD~1")
    (repo / "test_b.py").write_text("def test_b(): pass\n", encoding="utf-8")
    git(repo, "add", "test_b.py")
    git(repo, "reset", "-q", "--soft", "HEAD")  # index holds test_b.py on top of A
    git(repo, "update-ref", "refs/heads/side", "work")  # HEAD jumps to B, index untouched
    assert index_guard.main(["-C", str(repo), "check"]) == 1


def test_untracked_files_do_not_trip_guard(repo):
    (repo / "scratch.txt").write_text("x", encoding="utf-8")
    assert index_guard.is_clean(repo)


def test_verify_discard_resets_only_when_identical(repo, capsys):
    stale(repo)
    rc = index_guard.main(["-C", str(repo), "verify-discard", "--ref", "HEAD~1", "--reset"])
    assert rc == 0
    assert index_guard.is_clean(repo)
    # working tree untouched by the reset: the fix is still on disk
    assert "refuse()" in (repo / "test_a.py").read_text(encoding="utf-8")


def test_verify_discard_refuses_when_index_holds_unsaved_work(repo):
    stale(repo)
    (repo / "mine.py").write_text("orchestrator work\n", encoding="utf-8")
    git(repo, "add", "mine.py")
    rc = index_guard.main(["-C", str(repo), "verify-discard", "--ref", "HEAD~1", "--reset"])
    assert rc == 1
    assert "mine.py" in git(repo, "diff", "--cached", "--name-only")  # not destroyed


def test_verify_discard_without_reset_leaves_index(repo):
    stale(repo)
    assert index_guard.main(["-C", str(repo), "verify-discard", "--ref", "HEAD~1"]) == 0
    assert not index_guard.is_clean(repo)


def test_bad_ref_and_non_repo_are_git_errors(repo, tmp_path_factory):
    assert index_guard.main(["-C", str(repo), "verify-discard", "--ref", "nope"]) == 2
    plain = tmp_path_factory.mktemp("plain")
    assert index_guard.main(["-C", str(plain), "check"]) == 2
