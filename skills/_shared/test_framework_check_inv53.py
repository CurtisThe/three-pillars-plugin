"""Invariant 53 of framework-check.sh: the living-doc guard on a tp/* branch (Task 1.10).

Runs `framework-check.sh --only 53` in a copy of this tree's check script and modules, inside a
tiny git repo with an origin. rc 1 of the guard fails; rc 2 (no base ref) only warns.

Run with: pytest skills/_shared/test_framework_check_inv53.py -q
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
_ROOT = _SHARED.parent.parent
_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != "GITHUB_HEAD_REF"}
_ENV.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
             "GIT_COMMITTER_EMAIL": "t@t"})
KI = "three-pillars-docs/known_issues.md"


def _git(cwd, *args) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, env=_ENV)


def _tree(tmp_path: Path, with_origin: bool = True) -> Path:
    repo = tmp_path / "tree"
    (repo / "skills" / "_shared").mkdir(parents=True)
    shutil.copy(_ROOT / "framework-check.sh", repo / "framework-check.sh")
    for f in _SHARED.glob("*.py"):
        if not f.name.startswith("test_"):
            shutil.copy(f, repo / "skills" / "_shared" / f.name)
    shutil.copytree(_ROOT / "skills" / "tp-merge-from-main" / "scripts",
                    repo / "skills" / "tp-merge-from-main" / "scripts",
                    ignore=shutil.ignore_patterns("test_*", "__py" + "cache__"))
    (repo / "three-pillars-docs").mkdir()
    (repo / KI).write_text("# Known issues\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    if with_origin:
        origin = tmp_path / "origin.git"
        _git(tmp_path, "init", "-q", "--bare", "-b", "master", str(origin))
        _git(repo, "remote", "add", "origin", str(origin))
        _git(repo, "push", "-q", "-u", "origin", "master")
        _git(repo, "remote", "set-head", "origin", "master")
    return repo


def _branch_edit(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "tp/demo")
    (repo / KI).write_text("# Known issues\n\n### M1: edited\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "edit a living doc")


def _run(repo: Path):
    return subprocess.run(["bash", "framework-check.sh", "--only", "53"], cwd=repo,
                          capture_output=True, text=True, env=_ENV)


def test_inv53_fails_the_same_fixture_commit(tmp_path):
    repo = _tree(tmp_path)
    _branch_edit(repo)
    p = _run(repo)
    assert p.returncode != 0, p.stdout + p.stderr
    assert "FAIL: invariant 53:" in p.stderr
    assert "Traceback" not in p.stderr


def test_inv53_warns_without_base_ref(tmp_path):
    repo = _tree(tmp_path, with_origin=False)
    _branch_edit(repo)
    p = _run(repo)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "WARN: invariant 53:" in p.stderr


def test_inv53_passes_on_master(tmp_path):
    repo = _tree(tmp_path)
    p = _run(repo)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "invariant 53:" not in p.stderr
