"""test_numbering_carry.py -- Task 2.5: the carry certifier accepts a numbering commit.

design: basesync-autoresolve-coverage, Task 2.5.

A commit made by ``number_issues.py --commit`` against a base on the base branch is a certified
link (``base_sync_cert._certify_link_unchecked``), so the approval chain crosses it. A tampered,
foreign or forged-trailer single-parent commit is not. Real tmp repos only.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import numbering_carry as nc  # noqa: E402
import task_scope  # noqa: E402
from base_sync_cert import _certify_link_unchecked, _make_default_git  # noqa: E402
from task_scope import _git_env as clean_git_env  # noqa: E402 -- shipped scrub; git_env is dev-only

KI = "three-pillars-docs/known_issues.md"
RM = "three-pillars-docs/product_roadmap.md"
CLI = str(Path(__file__).resolve().parent / "number_issues.py")
IDENT = {
    "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@test",
    "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@test",
}
SUBJECT = "chore(ids): number issue IDs"


@pytest.fixture(autouse=True)
def _scrub_git_env(monkeypatch):
    for key in task_scope._GIT_LOCAL_ENV:       # the cert's default git seam reads os.environ
        monkeypatch.delenv(key, raising=False)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], env=clean_git_env(**IDENT),
                          capture_output=True, text=True, check=True).stdout.strip()


def _put(repo: Path, rel: str, text: str) -> None:
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(text, encoding="utf-8")


def _commit(repo: Path, msg: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


class Scenario:
    """master adds ``### M48``; ``feature`` adds ``### M-new-x`` + a roadmap citation (h0), then
    the numbering CLI commits h1. ``origin/master`` points at master."""

    def __init__(self, tmp_path: Path):
        self.repo = repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "master")
        _put(repo, KI, "### M47: existing\n")
        _put(repo, RM, "roadmap\n")
        self.c0 = _commit(repo, "c0")
        _git(repo, "checkout", "-q", "-b", "feature")
        _put(repo, KI, "### M47: existing\n\n### M-new-x: new\n")
        _put(repo, RM, "roadmap, see M-new-x\n")
        self.h0 = _commit(repo, "branch work")
        _git(repo, "checkout", "-q", "master")
        _put(repo, KI, "### M47: existing\n\n### M48: landed on base\n")
        self.base = _commit(repo, "base lands M48")
        _git(repo, "update-ref", "refs/remotes/origin/master", "master")
        _git(repo, "checkout", "-q", "feature")
        done = subprocess.run([sys.executable, CLI, "--repo", str(repo), "--base", "master",
                               "--commit"], env=clean_git_env(**IDENT), capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        self.h1 = _git(repo, "rev-parse", "HEAD")
        self.tree = _git(repo, "rev-parse", f"{self.h1}^{{tree}}")

    def check(self, h0: str, h1: str):
        return _certify_link_unchecked(self.repo, h0, h1, base_ref="master")

    def forge(self, message: str, parent: "str | None" = None, tree: "str | None" = None) -> str:
        return _git(self.repo, "commit-tree", tree or self.tree, "-p", parent or self.h0, "-m", message)


def test_numbering_commit_is_a_certified_link(tmp_path):
    s = Scenario(tmp_path)
    assert _git(s.repo, "show", f"{s.h1}:{KI}") == "### M47: existing\n\n### M49: new"
    link = s.check(s.h0, s.h1)
    assert link.ok, link.reason
    assert link.reason == ""
    assert nc.numbering_trailer(_make_default_git(s.repo), s.h1) == s.base


def test_amended_numbering_commit_with_one_extra_edit_is_refused(tmp_path):
    s = Scenario(tmp_path)
    _git(s.repo, "checkout", "-q", "-b", "tamper", s.h1)
    _put(s.repo, RM, "roadmap, see M49 and an extra edit\n")
    _git(s.repo, "add", "-A")
    _git(s.repo, "commit", "-q", "--amend", "--no-edit")
    tampered = _git(s.repo, "rev-parse", "HEAD")
    link = s.check(s.h0, tampered)
    assert not link.ok
    assert "numbering" in link.reason


def test_extra_file_in_the_numbering_commit_is_refused(tmp_path):
    s = Scenario(tmp_path)
    _git(s.repo, "checkout", "-q", "-b", "extra", s.h1)
    _put(s.repo, "three-pillars-docs/other.md", "smuggled\n")
    _git(s.repo, "add", "-A")
    _git(s.repo, "commit", "-q", "--amend", "--no-edit")
    link = s.check(s.h0, _git(s.repo, "rev-parse", "HEAD"))
    assert not link.ok and "numbering" in link.reason


def test_ordinary_single_parent_commit_fails_as_before(tmp_path):
    s = Scenario(tmp_path)
    _git(s.repo, "checkout", "-q", "-b", "plain", s.h0)
    _put(s.repo, RM, "roadmap, plain edit\n")
    plain = _commit(s.repo, "an ordinary commit")
    assert nc.numbering_trailer(_make_default_git(s.repo), plain) is None
    link = s.check(s.h0, plain)
    assert not link.ok
    assert link.reason == "merge shape: expected 2 parents, found 1"


def test_numbering_commit_whose_parent_is_not_h0_is_refused(tmp_path):
    s = Scenario(tmp_path)
    link = s.check(s.c0, s.h1)
    assert not link.ok and "numbering" in link.reason


def test_trailer_not_an_ancestor_of_the_base_branch_is_refused_without_planning(tmp_path, monkeypatch):
    s = Scenario(tmp_path)
    _git(s.repo, "checkout", "-q", "-b", "side", s.c0)
    _put(s.repo, KI, "### M47: existing\n\n### M48: landed on base\n")   # same tree as base
    side = _commit(s.repo, "a side-branch twin of the base commit")
    assert _git(s.repo, "rev-parse", f"{side}^{{tree}}") == _git(s.repo, "rev-parse", f"{s.base}^{{tree}}")
    forged = s.forge(f"{SUBJECT}\n\nNumbered-against: {side}\n")
    planned = []
    monkeypatch.setattr(nc, "plan_numbering", lambda *a, **k: planned.append(1) or {})
    link = s.check(s.h0, forged)
    assert not link.ok
    assert "Numbered-against" in link.reason
    assert planned == []


@pytest.mark.parametrize("message", [
    f"{SUBJECT}\n",                                       # trailer missing
    f"{SUBJECT}\n\nNumbered-against: not-a-sha\n",        # malformed
    f"{SUBJECT}\n\nNumbered-against: --all\n",            # option-shaped
])
def test_missing_or_malformed_trailer_is_refused(tmp_path, message):
    s = Scenario(tmp_path)
    link = s.check(s.h0, s.forge(message))
    assert not link.ok and "numbering" in link.reason


def test_trailer_on_a_commit_with_another_subject_is_not_a_numbering_commit(tmp_path):
    s = Scenario(tmp_path)
    forged = s.forge(f"wip\n\nNumbered-against: {s.base}\n")
    assert nc.numbering_trailer(_make_default_git(s.repo), forged) is None
    link = s.check(s.h0, forged)
    assert not link.ok and link.reason == "merge shape: expected 2 parents, found 1"


def test_none_trailer_plans_against_no_base(tmp_path):
    s = Scenario(tmp_path)
    _git(s.repo, "checkout", "-q", "-b", "nonebase", s.h0)
    _put(s.repo, KI, "### M47: existing\n\n### M48: new\n")        # numbered with no base: M48
    _put(s.repo, RM, "roadmap, see M48\n")
    _git(s.repo, "add", "-A")
    tree = _git(s.repo, "write-tree")
    ok = s.forge(f"{SUBJECT}\n\nNumbered-against: none\n", tree=tree)
    assert s.check(s.h0, ok).ok
    wrong = s.forge(f"{SUBJECT}\n\nNumbered-against: {s.base}\n", tree=tree)   # M49 expected against base
    link = s.check(s.h0, wrong)
    assert not link.ok and "numbering" in link.reason
