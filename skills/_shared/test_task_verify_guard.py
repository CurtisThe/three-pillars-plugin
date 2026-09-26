"""test_task_verify_guard.py — attempt placement passes the worktree isolation guard.

design: local-implement-and-review

Every attempt worktree lives under ``<dispatcher>/.claude/worktrees/tp-attempt-``:
there the isolation guard (inv #32) sees an agent-style worktree (case 5) and a
hooked commit passes, while a worktree anywhere else (the ``/tmp`` control) is
classified as the seat and refused once a ``tp/<slug>`` worktree is live. Real tmp
repos only; the ambient repository is never read (M23).
"""
from __future__ import annotations

import os
from pathlib import Path

import task_attempts
import worktree_isolation_guard as guard
from attempt_fixture import DD, SLUG, agent_worktree, git, make_seat, porcelain


def _open_and_assert_guard(dispatcher: Path, seat: Path) -> dict:
    att = task_attempts.open_attempt(dispatcher, "1.1", DD)
    adir = Path(att["attempt_dir"])
    prefix = os.path.join(os.path.realpath(dispatcher), ".claude", "worktrees", "tp-attempt-")
    assert str(adir).startswith(prefix)
    assert adir.name.startswith(f"tp-attempt-{SLUG}-1.1-")
    assert adir.is_dir()
    assert att["branch"].startswith(f"tp-attempt/{SLUG}/1.1-")
    assert git(adir, "rev-parse", "--abbrev-ref", "HEAD") == att["branch"]
    assert git(adir, "rev-parse", "HEAD") == git(dispatcher, "rev-parse", "HEAD")
    ok, msg = guard.assert_own_worktree(
        cwd=str(adir), worktree_porcelain=porcelain(seat), current_branch=att["branch"])
    assert (ok, msg) == (True, "")
    return att


def test_attempt_in_design_worktree_passes_guard(tmp_path):
    seat, wt = make_seat(tmp_path)
    _open_and_assert_guard(wt, seat)


def test_attempt_in_agent_worktree_passes_guard(tmp_path):
    seat, _wt = make_seat(tmp_path)
    agent = agent_worktree(seat)
    att = _open_and_assert_guard(agent, seat)
    assert f"{os.sep}agent-x{os.sep}.claude{os.sep}worktrees{os.sep}" in att["attempt_dir"]


def test_tmp_worktree_fails_guard(tmp_path):
    seat, _wt = make_seat(tmp_path)
    stray = tmp_path / "outside" / "tp-attempt-demo-1.1-deadbeef"
    git(seat, "worktree", "add", "-q", "-b", "tp-attempt/demo/1.1-deadbeef", str(stray))
    ok, msg = guard.assert_own_worktree(
        cwd=str(stray), worktree_porcelain=porcelain(seat),
        current_branch="tp-attempt/demo/1.1-deadbeef")
    assert ok is False
    assert "refusing commit" in msg
