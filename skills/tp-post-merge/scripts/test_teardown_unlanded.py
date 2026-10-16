"""Tests for teardown.py's unlanded-commit refusal.

design: review-log-survives-teardown (Task 2.5). A verified-merged design whose
`tp/<slug>` branch holds a commit on no remote-tracking ref (an unpushed review-log
flush) is refused with nothing deleted; once pushed, teardown proceeds.

Run with: pytest skills/tp-post-merge/scripts/test_teardown_unlanded.py -q
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


def _wt(seat: Path) -> Path:
    return seat.parent / "wt" / SLUG


def _tear(seat: Path) -> tuple[int, dict]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = teardown.main(["--slug", SLUG, "--base", "master", "--root", str(seat)])
    return rc, json.loads(buf.getvalue())


@pytest.fixture(autouse=True)
def _merged(monkeypatch):
    monkeypatch.setattr(teardown, "verify_merged", lambda *a, **k: True)


def _log_commit(seat: Path) -> None:
    _commit(_wt(seat), "three-pillars-docs/completed-tp-designs/demo/decisions.md",
            "log\n", "flush review log")


def test_unpushed_log_commit_is_not_lost(seat):
    _log_commit(seat)
    rc, payload = _tear(seat)
    assert rc == 1
    assert "steps" not in payload
    assert len(payload["unlanded"]) == 1
    assert "1 commit" in payload["refused"]
    assert "land these commits on master" in payload["remedy"]
    assert "already on master" in payload["remedy"]
    assert "delete the branch by hand" in payload["remedy"]
    assert _git(seat, "branch", "--list", BRANCH).stdout.strip()
    assert teardown.worktree_paths(seat, SLUG)
    assert SLUG in (seat / ".claude" / "last-design").read_text(encoding="utf-8")
    assert _git(seat, "ls-remote", "--heads", "origin", BRANCH).stdout.strip()


def test_pushed_log_commit_tears_down(seat):
    _log_commit(seat)
    _git(_wt(seat), "push", "-q", "origin", BRANCH)
    rc, payload = _tear(seat)
    assert rc == 0
    assert "steps" in payload
    assert not _git(seat, "branch", "--list", BRANCH).stdout.strip()


def test_unlanded_listing_failure_refuses(seat, monkeypatch):
    def boom(root, slug):
        raise teardown.Unobservable("git rev-list exited 128: boom")
    monkeypatch.setattr(teardown, "unlanded_commits", boom)
    rc, payload = _tear(seat)
    assert rc == 1
    assert payload["unlanded"] == []
    assert "boom" in payload["refused"]
    assert _git(seat, "branch", "--list", BRANCH).stdout.strip()
    assert teardown.worktree_paths(seat, SLUG)


def _unlanded_cli(seat: Path) -> tuple[int, dict]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = teardown.main(["--unlanded", "--slug", SLUG, "--root", str(seat)])
    return rc, json.loads(buf.getvalue())


def test_unlanded_cli_lists_and_exits_1(seat):
    _log_commit(seat)
    rc, payload = _unlanded_cli(seat)
    assert rc == 1
    assert len(payload["unlanded"]) == 1


def test_unlanded_cli_clean_exits_0(seat):
    assert _unlanded_cli(seat) == (0, {"unlanded": []})


def test_unlanded_cli_listing_failure_exits_3(seat, monkeypatch):
    def boom(root, slug):
        raise teardown.Unobservable("listing failed: boom")
    monkeypatch.setattr(teardown, "unlanded_commits", boom)
    rc, payload = _unlanded_cli(seat)
    assert rc == 3
    assert "boom" in payload["error"]
