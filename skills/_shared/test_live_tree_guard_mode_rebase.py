"""live_tree_guard: the worktree mode survives a restore, and `rebase` re-baselines.

design: cheap-tier-offload (PR #191 review r3). A dirty executable file the drafter
rewrote must come back with its exec bit, and a path the caller changed itself (an
accepted cheap fix) is the new baseline once `rebase` records it.
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import live_tree_guard as ltg  # noqa: E402


def _git(cwd, *args) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "feat")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    (root / "run.sh").write_text("#!/bin/sh\necho 1\n", encoding="utf-8")
    (root / "run.sh").chmod(0o755)
    (root / "a.py").write_text("a\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


def _exec(path: Path) -> bool:
    return bool(os.stat(path).st_mode & stat.S_IXUSR)


def test_restore_keeps_the_exec_bit_of_a_dirty_snapshot_path(repo, tmp_path):
    run = repo / "run.sh"
    run.write_text("#!/bin/sh\necho 1\necho 2\n", encoding="utf-8")  # an applied fix
    ltg.snapshot(repo, tmp_path / "store")
    run.write_text("#!/bin/sh\necho drafter\n", encoding="utf-8")
    v = ltg.guard(repo, tmp_path / "store")
    assert v["ok"] is False and v["paths"] == ["run.sh"] and v["unrestored"] == [], v
    assert run.read_text(encoding="utf-8") == "#!/bin/sh\necho 1\necho 2\n"
    assert _exec(run), "restore dropped the exec bit"
    assert "mode change" not in _git(repo, "diff", "--summary")


def test_a_drafter_chmod_of_a_dirty_path_is_caught_and_undone(repo, tmp_path):
    run = repo / "run.sh"
    run.write_text("#!/bin/sh\necho 2\n", encoding="utf-8")
    ltg.snapshot(repo, tmp_path / "store")
    run.chmod(0o644)
    v = ltg.guard(repo, tmp_path / "store")
    assert v["ok"] is False and v["paths"] == ["run.sh"], v
    assert _exec(run)


def test_rebase_makes_the_callers_own_change_the_baseline(repo, tmp_path):
    store = tmp_path / "store"
    ltg.snapshot(repo, store)
    (repo / "a.py").write_text("fixed\n", encoding="utf-8")  # the caller's accepted fix
    ltg.rebase(repo, store, ["a.py"])
    assert ltg.guard(repo, store)["ok"] is True
    (repo / "a.py").write_text("weakened\n", encoding="utf-8")  # a later drafter write
    v = ltg.guard(repo, store)
    assert v["ok"] is False and v["paths"] == ["a.py"], v
    assert (repo / "a.py").read_text(encoding="utf-8") == "fixed\n"


def test_rebase_without_a_snapshot_raises(repo, tmp_path):
    with pytest.raises(ltg.GuardError):
        ltg.rebase(repo, tmp_path / "nowhere", ["a.py"])
