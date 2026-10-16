"""test_archive_allowlist_uncommitted.py — `apply` never loses uncommitted work.

PR #177 r2: `apply` runs `git rm -f` (so a design-complete staged `git mv`
rename can be removed), and `-f` skips git's lost-work check. `apply` refuses
instead — `UncommittedDropError`, nothing removed — when any drop's working-tree
file differs from the index or its index blob is in no HEAD tree. Both CLIs
(`archive_allowlist.py apply`, `archive_sweep.py --apply`) exit 1 on refusal.

Run with: python -m pytest skills/_shared/test_archive_allowlist_uncommitted.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from archive_allowlist import UncommittedDropError, apply, plan_prune

HERE = Path(__file__).resolve().parent
LIVE = "three-pillars-docs/tp-designs/x"
DD = "three-pillars-docs/completed-tp-designs/x"
NOTES = DD + "/demos/notes.txt"


def _env():
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          text=True, check=True, env=_env())


def _archived(root: Path) -> Path:
    """Commit a design with a drop candidate, then `git mv` it (design-complete 6c)."""
    _git(root, "init", "-q", "-b", "master")
    d = root / LIVE
    (d / "demos").mkdir(parents=True)
    (d / "design.md").write_text("d\n", encoding="utf-8")
    (d / "demos" / "notes.txt").write_text("v1\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "-c", "user.name=f", "-c", "user.email=f@t", "commit", "-q", "-m", "base")
    (root / "three-pillars-docs" / "completed-tp-designs").mkdir()
    _git(root, "mv", LIVE, DD)
    return root / NOTES


def _assert_refused_and_kept(root: Path, wip: Path, text: str):
    plan = plan_prune(DD, root)
    assert plan.drop == [NOTES]
    with pytest.raises(UncommittedDropError) as exc:
        apply(plan, root)
    assert exc.value.paths == [NOTES]
    assert wip.read_text(encoding="utf-8") == text
    assert NOTES in _git(root, "ls-files", "--", DD).stdout.split()


def test_unstaged_edit_of_a_drop_refuses(tmp_path: Path):
    wip = _archived(tmp_path)
    wip.write_text("v1\nUNCOMMITTED WIP\n", encoding="utf-8")
    _assert_refused_and_kept(tmp_path, wip, "v1\nUNCOMMITTED WIP\n")


def test_staged_edit_of_a_drop_refuses(tmp_path: Path):
    wip = _archived(tmp_path)
    wip.write_text("v1\nSTAGED WIP\n", encoding="utf-8")
    _git(tmp_path, "add", "--", NOTES)
    _assert_refused_and_kept(tmp_path, wip, "v1\nSTAGED WIP\n")


def test_pure_staged_rename_is_removed(tmp_path: Path):
    wip = _archived(tmp_path)
    apply(plan_prune(DD, tmp_path), tmp_path)
    assert not wip.exists()
    assert _git(tmp_path, "ls-files", "--", DD).stdout.split() == [DD + "/design.md"]


@pytest.mark.parametrize("argv", [
    ["archive_allowlist.py", "apply", "--design-dir", DD],
    ["archive_sweep.py", "--apply"],
])
def test_cli_exits_1_and_removes_nothing(tmp_path: Path, argv):
    wip = _archived(tmp_path)
    wip.write_text("v1\nUNCOMMITTED WIP\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(HERE / argv[0]), *argv[1:],
                        "--repo-root", str(tmp_path)],
                       capture_output=True, text=True, env=_env(), cwd=tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "uncommitted" in r.stderr
    assert wip.read_text(encoding="utf-8") == "v1\nUNCOMMITTED WIP\n"
