"""Tests for scratch_root — the one scratch base (design: launch-role-precedence 3.1)."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scratch_root as sr  # noqa: E402


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def _init(path):
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@t")
    _git(path, "config", "user.name", "t")
    return path


def _exclude_lines(root):
    common = Path(_git(root, "rev-parse", "--git-common-dir").strip())
    if not common.is_absolute():
        common = root / common
    f = common / "info" / "exclude"
    return f.read_text(encoding="utf-8").splitlines() if f.exists() else []


def _touch_scratch(root):
    p = root / ".tp-scratch" / "child-spawn" / "x"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x")


def test_constants():
    assert sr.SCRATCH_DIR == ".tp-scratch"
    assert sr.CHILD_SPAWN_DIR == ".tp-scratch/child-spawn"
    assert sr.LEGACY_DIR == ".claude/worktrees"
    assert sr.ignore_line() == "/.tp-scratch/"


def test_no_claude_component(tmp_path):
    assert ".claude" not in Path(sr.parent(tmp_path)).parts
    assert ".claude" not in Path(sr.CHILD_SPAWN_DIR).parts


def test_scan_parents_order(tmp_path):
    got = [Path(p) for p in sr.scan_parents(tmp_path)]
    assert got == [Path(sr.parent(tmp_path)), tmp_path / ".claude" / "worktrees"]


def test_is_under_scratch():
    assert sr.is_under_scratch("/r/.tp-scratch/tp-attempt-x")
    assert not sr.is_under_scratch("/r/.claude/worktrees/agent-a1")
    assert not sr.is_under_scratch("/r/src/x.py")


def test_ensure_excluded_hides_scratch(tmp_path):
    root = _init(tmp_path / "repo")
    _touch_scratch(root)
    assert ".tp-scratch" in _git(root, "status", "--porcelain")
    assert sr.ensure_excluded(root) is True
    assert _git(root, "status", "--porcelain").strip() == ""


def test_ensure_excluded_idempotent(tmp_path):
    root = _init(tmp_path / "repo")
    sr.ensure_excluded(root)
    sr.ensure_excluded(root)
    assert _exclude_lines(root).count("/.tp-scratch/") == 1


def test_ensure_excluded_noop_when_gitignored(tmp_path):
    root = _init(tmp_path / "repo")
    (root / ".gitignore").write_text("/.tp-scratch/\n")
    assert sr.ensure_excluded(root) is True
    assert _exclude_lines(root).count("/.tp-scratch/") == 0


def test_ensure_excluded_from_linked_worktree(tmp_path):
    root = _init(tmp_path / "repo")
    (root / "f").write_text("f")
    _git(root, "add", "f")
    _git(root, "commit", "-q", "-m", "init")
    wt = tmp_path / "wt"
    _git(root, "worktree", "add", "-q", "-b", "b", str(wt))
    assert sr.ensure_excluded(wt) is True
    assert _exclude_lines(root).count("/.tp-scratch/") == 1


def test_ensure_excluded_non_repo_returns_false(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert sr.ensure_excluded(plain) is False
