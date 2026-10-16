"""PR #206 round 2: the numbering commit holds only the plan, and a non-UTF-8 doc is skipped.

(1) `--commit` ran a bare `git commit`, so anything the operator had already staged rode along
in the `chore(ids)` commit, which `numbering_carry` then refused as a certified link. (2) The
tree-wide scope read every committed `.md` with locale decoding, so one non-UTF-8 file anywhere
crashed the CLI with a traceback. Both the CLI and the certifier now skip such a file. Real tmp
repos only.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import task_scope  # noqa: E402
from base_sync_cert import _certify_link_unchecked  # noqa: E402
from task_scope import _git_env  # noqa: E402

CLI = str(Path(__file__).resolve().parent / "number_issues.py")
IDENT = {"GIT_AUTHOR_NAME": "f", "GIT_AUTHOR_EMAIL": "f@t",
         "GIT_COMMITTER_NAME": "f", "GIT_COMMITTER_EMAIL": "f@t"}
KI = "three-pillars-docs/known_issues.md"
LATIN1 = "vendor/legacy/CHANGES.md"


@pytest.fixture(autouse=True)
def _scrub_git_env(monkeypatch):
    for key in task_scope._GIT_LOCAL_ENV:       # the cert's default git seam reads os.environ
        monkeypatch.delenv(key, raising=False)


def _git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], env=_git_env(**IDENT),
                          capture_output=True, check=True).stdout.decode("utf-8", "replace")


def _put(repo, rel, data: bytes):
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_bytes(data)


def _number(repo):
    return subprocess.run([sys.executable, CLI, "--repo", str(repo), "--base", "master",
                           "--commit"], env=_git_env(**IDENT), capture_output=True, text=True)


def _scenario(tmp_path, extra=None):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    _put(repo, KI, b"### M47: existing\n")
    _put(repo, "other.txt", b"x\n")
    for rel, data in (extra or {}).items():
        _put(repo, rel, data)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "c0")
    _git(repo, "update-ref", "refs/remotes/origin/master", "master")
    _git(repo, "checkout", "-qb", "feature")
    _put(repo, KI, b"### M47: existing\n\n### M-new-x: new\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "branch")
    return repo, _git(repo, "rev-parse", "HEAD").strip()


def test_commit_leaves_prestaged_unrelated_files_out(tmp_path):
    repo, h0 = _scenario(tmp_path)
    _put(repo, "other.txt", b"smuggled\n")
    _git(repo, "add", "other.txt")
    done = _number(repo)
    assert done.returncode == 0, done.stderr
    h1 = _git(repo, "rev-parse", "HEAD").strip()
    assert _git(repo, "diff", "--name-only", h0, h1).split() == [KI]
    assert _git(repo, "diff", "--cached", "--name-only").split() == ["other.txt"]
    assert _certify_link_unchecked(repo, h0, h1, base_ref="master").ok


def test_a_non_utf8_md_outside_the_issue_docs_does_not_crash_numbering(tmp_path):
    repo, h0 = _scenario(tmp_path, {LATIN1: b"caf\xe9 -- a Latin-1 vendored changelog\n"})
    done = _number(repo)
    assert done.returncode == 0, done.stderr
    assert "### M48: new" in _git(repo, "show", f"HEAD:{KI}")
    h1 = _git(repo, "rev-parse", "HEAD").strip()
    link = _certify_link_unchecked(repo, h0, h1, base_ref="master")
    assert link.ok, link.reason
