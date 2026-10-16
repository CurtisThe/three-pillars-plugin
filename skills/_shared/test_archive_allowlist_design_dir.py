"""test_archive_allowlist_design_dir.py — could-not-evaluate is never a clean plan.

Post-converge fix F2 of archive-slimming. `plan`/`apply` refuse (exit 2, a
message naming the dir) when `--design-dir` does not exist, is not an archived
`completed-tp-designs/<slug>` dir, or holds no tracked file — the state a
stash leaves behind after design-complete's staged `git mv`, which used to
print `total: 0 bytes` and exit 0. The uncommitted-drop refusal's remedy never
suggests a stash. `archive_sweep` skips (and names) an archived dir with no
tracked file instead of failing the whole sweep.

Run with: python3 -m pytest skills/_shared/test_archive_allowlist_design_dir.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from archive_allowlist import DesignDirError, plan_prune

HERE = Path(__file__).resolve().parent
LIVE = "three-pillars-docs/tp-designs/x"
DD = "three-pillars-docs/completed-tp-designs/x"


def _env():
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), "-c", "user.name=f", "-c",
                           "user.email=f@t", *args], capture_output=True,
                          text=True, check=True, env=_env())


def _cli(root, script, *argv):
    return subprocess.run([sys.executable, str(HERE / script), *argv,
                           "--repo-root", str(root)], capture_output=True,
                          text=True, env=_env(), cwd=root)


def _repo(root: Path) -> Path:
    """A committed live design with a drop candidate and an ignored handoff."""
    _git(root, "init", "-q", "-b", "master")
    (root / ".gitignore").write_text("three-pillars-docs/*/*/handoff.md\n", encoding="utf-8")
    d = root / LIVE
    (d / "demos").mkdir(parents=True)
    (d / "design.md").write_text("d\n", encoding="utf-8")
    (d / "demos" / "notes.txt").write_text("v1\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "base")
    (d / "handoff.md").write_text("local session state\n", encoding="utf-8")
    (root / DD).parent.mkdir(parents=True)
    return root


@pytest.mark.parametrize("action", ["plan", "apply"])
def test_nonexistent_design_dir_refuses(tmp_path, action):
    root = _repo(tmp_path)
    r = _cli(root, "archive_allowlist.py", action, "--design-dir", DD)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "no such directory" in r.stderr and DD in r.stderr
    assert "total:" not in r.stdout
    with pytest.raises(DesignDirError):
        plan_prune(DD, root)


@pytest.mark.parametrize("action", ["plan", "apply"])
def test_non_archived_design_dir_refuses(tmp_path, action):
    root = _repo(tmp_path)
    r = _cli(root, "archive_allowlist.py", action, "--design-dir", LIVE)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "not an archived design dir" in r.stderr
    assert (root / LIVE / "demos" / "notes.txt").exists()
    assert "total:" not in r.stdout


def test_reverted_rename_refuses_instead_of_an_empty_plan(tmp_path):
    root = _repo(tmp_path)
    _git(root, "mv", LIVE, DD)
    (root / DD / "demos" / "notes.txt").write_text("v1\nWIP\n", encoding="utf-8")
    _git(root, "stash", "push", "-q", "-m", "fixture-only")  # the unsafe old advice
    assert (root / DD / "handoff.md").exists()  # the ignored file keeps the dir
    r = _cli(root, "archive_allowlist.py", "plan", "--design-dir", DD, "--json")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "holds no tracked file" in r.stderr
    assert r.stdout == ""


def test_uncommitted_refusal_never_suggests_a_stash(tmp_path):
    root = _repo(tmp_path)
    _git(root, "mv", LIVE, DD)
    (root / DD / "demos" / "notes.txt").write_text("v1\nWIP\n", encoding="utf-8")
    r = _cli(root, "archive_allowlist.py", "apply", "--design-dir", DD)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "stash" not in r.stderr.lower()
    assert "git restore -- <path>" in r.stderr and DD + "/demos/notes.txt" in r.stderr
    # following the remedy (restore that path only) lets the re-run succeed
    subprocess.run(["git", "-C", str(root), "restore", "--", DD + "/demos/notes.txt"],
                   check=True, env=_env())
    again = _cli(root, "archive_allowlist.py", "apply", "--design-dir", DD)
    assert again.returncode == 0, again.stdout + again.stderr
    assert not (root / DD / "demos" / "notes.txt").exists()
    assert (root / DD / "design.md").exists()


def test_sweep_skips_an_untracked_only_archive_dir(tmp_path):
    root = _repo(tmp_path)
    _git(root, "mv", LIVE, DD)
    _git(root, "commit", "-q", "-m", "archive x")
    stray = root / "three-pillars-docs/completed-tp-designs/stray"
    stray.mkdir()
    (stray / "handoff.md").write_text("ignored only\n", encoding="utf-8")
    r = _cli(root, "archive_sweep.py")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "skipping" in r.stderr and "completed-tp-designs/stray" in r.stderr
    assert "x: 1 files" in r.stdout
