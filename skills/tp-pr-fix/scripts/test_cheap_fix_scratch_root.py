"""Tests for cheap_fix.py + review_prep_io.py — the drafter scratch moves to `.tp-scratch/`.

design: launch-role-precedence (Task 3.7). `cheap_fix.SCRATCH_DIR` and
`review_prep_io.SCRATCH_DIR` are the one scratch base (`scratch_root.SCRATCH_DIR`, no `.claude`
component), so a cheap-fix owner dir sits at `<root>/.tp-scratch/cheap-fix-<id>/r1`. Both call
`scratch_root.ensure_excluded(root)` before their `check-ignore` refusal — fail-open, so a
consumer repo with no `.gitignore` line still gets its scratch and stays clean for `git status`;
the not-gitignored error is then reachable only when that call fails, and names `.tp-scratch/`.
Nothing here starts a model.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import cheap_fix  # noqa: E402
import review_prep_io  # noqa: E402
import scratch_root  # noqa: E402

PR_URL = "https://github.com/o/r/pull/7"


def _git(cwd, *args) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout.strip()


def _repo(tmp_path, ignore: bool) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    (root / "a.py").write_text("broken", encoding="utf-8")
    if ignore:
        (root / ".gitignore").write_text(scratch_root.ignore_line() + "\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


# --- the one scratch base ---------------------------------------------------------------


def test_both_scratch_constants_are_the_scratch_base():
    assert cheap_fix.SCRATCH_DIR == review_prep_io.SCRATCH_DIR == scratch_root.SCRATCH_DIR
    assert ".claude" not in Path(cheap_fix.SCRATCH_DIR).parts


def test_prep_io_root_is_under_the_scratch_base(tmp_path):
    repo = _repo(tmp_path, ignore=True)
    assert review_prep_io.root(repo, PR_URL) == repo / ".tp-scratch" / "prep-io-7"


# --- cheap_fix.scratch -------------------------------------------------------------------


def test_owner_dir_is_under_the_scratch_base(tmp_path):
    repo = _repo(tmp_path, ignore=True)
    path = cheap_fix.scratch(repo, _git(repo, "rev-parse", "HEAD"))
    try:
        owner = path.resolve().parent
        assert owner.parent == (repo / ".tp-scratch").resolve()
        assert owner.name.startswith("cheap-fix-")
        assert _git(repo, "status", "--porcelain") == ""
    finally:
        cheap_fix.discard(path)


def test_a_repo_with_no_ignore_line_still_gets_a_scratch_and_stays_clean(tmp_path):
    """`ensure_excluded` is the first writer's job: the consumer repo has no `.gitignore`
    line, yet the scratch is made and `git status` reports nothing."""
    repo = _repo(tmp_path, ignore=False)
    path = cheap_fix.scratch(repo, _git(repo, "rev-parse", "HEAD"))
    try:
        assert path.is_dir()
        assert path.resolve().parent.parent == (repo / ".tp-scratch").resolve()
        assert _git(repo, "status", "--porcelain") == ""
        common = _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
        exclude = Path(common) / "info" / "exclude"
        assert exclude.read_text(encoding="utf-8").splitlines().count(
            scratch_root.ignore_line()) == 1
    finally:
        cheap_fix.discard(path)


def test_the_not_gitignored_error_needs_ensure_excluded_to_fail(tmp_path, monkeypatch):
    repo = _repo(tmp_path, ignore=False)
    monkeypatch.setattr(scratch_root, "ensure_excluded", lambda root: False)
    with pytest.raises(RuntimeError, match="not gitignored"):
        cheap_fix.scratch(repo, _git(repo, "rev-parse", "HEAD"))
    assert not (repo / ".tp-scratch").exists()


def test_refusal_message_names_the_scratch_base(tmp_path, monkeypatch):
    repo = _repo(tmp_path, ignore=False)
    monkeypatch.setattr(scratch_root, "ensure_excluded", lambda root: False)
    with pytest.raises(RuntimeError) as exc:
        cheap_fix.scratch(repo, _git(repo, "rev-parse", "HEAD"))
    assert ".tp-scratch/" in str(exc.value)
