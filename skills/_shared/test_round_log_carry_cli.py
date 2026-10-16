"""Tests for the `round_log_carry.py check` CLI (exit 0 accepted, 1 rejected, 2 error).

design: review-log-survives-teardown. The orchestrator pushes a Tier 7 log flush only
when this command accepts the new commit.

Run with: pytest skills/_shared/test_round_log_carry_cli.py -q
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent / "round_log_carry.py"
ARCHIVE = "three-pillars-docs/completed-tp-designs/demo"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def _commit(repo: Path, rel: str, text: str, msg: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _git(repo, "add", rel)
    _git(repo, "commit", "-q", "-m", msg)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "r"
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    for key, val in (("user.name", "t"), ("user.email", "t@example.com"),
                     ("commit.gpgsign", "false")):
        _git(root, "config", key, val)
    _commit(root, f"{ARCHIVE}/design.md", "d\n", "archive")
    return root


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def test_accepts_a_round_log_commit_at_head(repo):
    _commit(repo, f"{ARCHIVE}/decisions.md", "log\n", "flush")
    result = _run("check", "--repo", str(repo))
    assert result.returncode == 0, result.stderr


def test_accepts_an_explicit_rev(repo):
    _commit(repo, f"{ARCHIVE}/decisions.md", "log\n", "flush")
    sha = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "src/x.py", "x\n", "code")
    assert _run("check", "--repo", str(repo), sha).returncode == 0
    assert _run("check", "--repo", str(repo)).returncode == 1


def test_rejects_a_code_commit_with_reason(repo):
    _commit(repo, "src/x.py", "x\n", "code")
    result = _run("check", "--repo", str(repo))
    assert result.returncode == 1
    assert "outside the archive" in result.stdout


def test_rejects_a_root_commit(repo):
    result = _run("check", "--repo", str(repo))
    assert result.returncode == 1


def test_unknown_rev_is_an_error(repo):
    assert _run("check", "--repo", str(repo), "no-such-rev").returncode == 2


def test_not_a_repo_is_an_error(tmp_path):
    assert _run("check", "--repo", str(tmp_path / "missing")).returncode == 2


def test_usage_error_exits_2():
    assert _run().returncode == 2
    assert _run("bogus").returncode == 2
