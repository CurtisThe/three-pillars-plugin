"""Tests for teardown.py's verification through `evaluate` and its refusal report.

design: review-log-survives-teardown (Task 1.3). Seat fixture as in test_teardown.py:
a local bare origin, so the gh check is skipped and nothing touches the network.

Run with: pytest skills/tp-post-merge/scripts/test_teardown_refusal.py -q
"""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import teardown  # noqa: E402

SLUG = "demo"
BRANCH = f"tp/{SLUG}"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                          check=True)


def _commit(repo: Path, rel: str, text: str, msg: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _git(repo, "add", rel)
    _git(repo, "commit", "-q", "-m", msg)


@pytest.fixture
def seat(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    repo = tmp_path / "seat"
    subprocess.run(["git", "init", "-q", "-b", "master", str(repo)], check=True)
    for key, val in (("user.name", "t"), ("user.email", "t@example.com"),
                     ("commit.gpgsign", "false")):
        _git(repo, "config", key, val)
    _commit(repo, "README.md", "hi\n", "init")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-q", "origin", "master")
    _git(repo, "branch", BRANCH)
    _git(repo, "push", "-q", "origin", BRANCH)
    _git(repo, "worktree", "add", "-q", str(tmp_path / "wt" / SLUG), BRANCH)
    (repo / ".claude").mkdir()
    (repo / ".claude" / "last-design").write_text(f"other\n{SLUG}\n", encoding="utf-8")
    return repo


def _run(repo: Path) -> tuple[int, dict]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = teardown.main(["--slug", SLUG, "--base", "master", "--root", str(repo)])
    return rc, json.loads(buf.getvalue())


def _work_then_merge(repo: Path, flag: str) -> None:
    """Commit in the design worktree, push the branch, then merge it into master."""
    wt = repo.parent / "wt" / SLUG
    _commit(wt, "work.txt", "work\n", "design work")
    _git(wt, "push", "-q", "origin", BRANCH)
    _git(repo, "merge", flag, "-q", "-m", "merge design", BRANCH)
    _git(repo, "push", "-q", "origin", "master")


def _remote_has_branch(repo: Path) -> bool:
    return bool(_git(repo, "ls-remote", "--heads", "origin", BRANCH).stdout.strip())


def _intact(repo: Path) -> bool:
    return ((repo.parent / "wt" / SLUG).is_dir()
            and bool(_git(repo, "branch", "--list", BRANCH).stdout.strip())
            and _remote_has_branch(repo)
            and SLUG in (repo / ".claude" / "last-design").read_text(encoding="utf-8"))


def test_no_ff_merged_branch_tears_down(seat: Path) -> None:
    _work_then_merge(seat, "--no-ff")
    rc, out = _run(seat)
    assert rc == 0, out
    assert "steps" in out
    assert not (seat.parent / "wt" / SLUG).exists()
    assert not _git(seat, "branch", "--list", BRANCH).stdout.strip()
    assert not _remote_has_branch(seat)


def test_empty_branch_refusal_names_all_checks(seat: Path) -> None:
    rc, out = _run(seat)
    assert rc == 1
    assert "refused" in out
    assert {"archive", "gh", "ancestor"} <= set(out["checks"])
    assert "not github" in out["checks"]["gh"].lower()
    assert out["remedy"]
    assert _intact(seat)


def test_fast_forward_merge_refuses_with_remedy(seat: Path) -> None:
    _work_then_merge(seat, "--ff-only")
    rc, out = _run(seat)
    assert rc == 1
    assert out["remedy"]
    assert _intact(seat)
