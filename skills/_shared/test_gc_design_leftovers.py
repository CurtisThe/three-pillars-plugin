"""Tests for gc_design_leftovers: reap a merged design's leaked regress/rerun checkouts."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name("gc_design_leftovers.py")
RERUN_FOO = "tp-rerun/foo-0123abcd-a1b2c3"
RERUN_FOOBAR = "tp-rerun/foo-bar-0123abcd-a1b2c3"


def git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                       cwd=cwd, capture_output=True, text=True, check=True)
    return r.stdout


def make_seat(tmp_path: Path) -> Path:
    seat = tmp_path / "seat"
    seat.mkdir()
    git(seat, "init", "-q", "-b", "main")
    (seat / "a.txt").write_text("a\n")
    git(seat, "add", "a.txt")
    git(seat, "commit", "-q", "-m", "base")
    return seat


def add_wt(seat: Path, path: Path, branch: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    git(seat, "worktree", "add", "-q", "-b", branch, str(path))
    return path


def run(cwd: Path, *args: str) -> tuple[int, dict]:
    r = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd,
                       capture_output=True, text=True)
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1, r.stdout + r.stderr
    return r.returncode, json.loads(lines[0])


def branches(seat: Path) -> set[str]:
    return set(git(seat, "branch", "--format=%(refname:short)").split())


def build(tmp_path: Path):
    seat = make_seat(tmp_path)
    agent = add_wt(seat, seat / ".claude" / "worktrees" / "agent-a", "regress/foo")
    scratch = add_wt(seat, seat / ".tp-scratch" / "rr", RERUN_FOO)
    other = add_wt(seat, tmp_path / "elsewhere" / "rr2", RERUN_FOOBAR)
    cand = add_wt(seat, tmp_path / "elsewhere" / "c", "candidate/foo/single")
    git(seat, "branch", "regress/foo-orphan-not")  # not matching exactly: survives
    return seat, agent, scratch, other, cand


def test_dry_run_changes_nothing(tmp_path):
    seat, agent, scratch, other, cand = build(tmp_path)
    before = branches(seat)
    rc, out = run(seat, "--slug", "foo")
    assert rc == 0
    assert out["apply"] is False
    assert agent.is_dir() and scratch.is_dir()
    assert branches(seat) == before
    listed = json.dumps(out)
    assert "regress/foo" in listed and RERUN_FOO in listed
    assert RERUN_FOOBAR not in listed


def test_apply_removes_worktrees_even_dirty_and_branches(tmp_path):
    seat, agent, scratch, other, cand = build(tmp_path)
    (agent / "dirty.txt").write_text("x\n")
    git(seat, "worktree", "lock", str(scratch))
    rc, out = run(seat, "--slug", "foo", "--apply")
    assert rc == 0 and not out.get("error")
    assert not agent.exists() and not scratch.exists()
    left = branches(seat)
    assert "regress/foo" not in left and RERUN_FOO not in left


def test_other_designs_survive(tmp_path):
    seat, agent, scratch, other, cand = build(tmp_path)
    run(seat, "--slug", "foo", "--apply")
    left = branches(seat)
    assert RERUN_FOOBAR in left and "candidate/foo/single" in left
    assert "regress/foo-orphan-not" in left
    assert other.is_dir() and cand.is_dir()


def test_orphan_branches_deleted(tmp_path):
    seat = make_seat(tmp_path)
    git(seat, "branch", "regress/foo")
    git(seat, "branch", RERUN_FOO)
    git(seat, "branch", RERUN_FOOBAR)
    rc, out = run(seat, "--slug", "foo", "--apply")
    assert rc == 0
    assert branches(seat) == {"main", RERUN_FOOBAR}


def test_git_failure_exits_zero_with_error(tmp_path):
    notrepo = tmp_path / "plain"
    notrepo.mkdir()
    rc, out = run(notrepo, "--slug", "foo", "--apply")
    assert rc == 0
    assert out.get("error")
