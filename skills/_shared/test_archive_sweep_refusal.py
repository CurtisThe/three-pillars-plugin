"""test_archive_sweep_refusal.py — `archive_sweep --apply` prints its plan only
after a successful apply (post-converge fix F5 of archive-slimming).

A refused apply (a drop holding uncommitted content) exits 1 with the reason
on stderr and puts nothing of the plan on stdout, matching `archive_allowlist
apply`; a successful apply prints the plan it applied.

Run with: python3 -m pytest skills/_shared/test_archive_sweep_refusal.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
DD = "three-pillars-docs/completed-tp-designs/x"
NOTES = DD + "/demos/notes.txt"


def _env():
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), "-c", "user.name=f", "-c",
                           "user.email=f@t", *args], capture_output=True,
                          text=True, check=True, env=_env())


def _sweep(root, *argv):
    return subprocess.run([sys.executable, str(HERE / "archive_sweep.py"), *argv,
                           "--repo-root", str(root)], capture_output=True,
                          text=True, env=_env(), cwd=root)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    d = tmp_path / DD
    (d / "demos").mkdir(parents=True)
    (d / "design.md").write_text("d\n", encoding="utf-8")
    (d / "demos" / "notes.txt").write_text("v1\n", encoding="utf-8")
    _git(tmp_path, "init", "-q", "-b", "master")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "archive")
    return tmp_path


@pytest.mark.parametrize("fmt", [[], ["--json"]])
def test_refused_apply_prints_no_plan(repo, fmt):
    (repo / NOTES).write_text("v1\nWIP\n", encoding="utf-8")
    r = _sweep(repo, "--apply", *fmt)
    assert r.returncode == 1, r.stdout + r.stderr
    assert r.stdout == ""
    assert "uncommitted" in r.stderr and NOTES in r.stderr
    assert (repo / NOTES).read_text(encoding="utf-8") == "v1\nWIP\n"


def test_successful_apply_prints_the_plan(repo):
    r = _sweep(repo, "--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "x: 1 files, 3 bytes" in r.stdout and "total: 3 bytes" in r.stdout
    assert not (repo / NOTES).exists()
