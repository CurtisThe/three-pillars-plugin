"""Task 1.7: the isolation guard exempts a non-tp branch in a `-wt/` worktree.

Hermetic: worktree-list porcelain strings only, no real git worktrees.
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr
from unittest.mock import patch

from worktree_isolation_guard import assert_own_worktree, main

SEAT = "/home/user/repo"
CHORE_WT = "/home/user/repo-wt/automated-upgrades-on"
TP_WT = "/home/user/repo-wt/a"


def _entry(path: str, branch: str | None, bare: bool = False) -> str:
    lines = [f"worktree {path}", "HEAD abc123"]
    if bare:
        lines.append("bare")
    if branch:
        lines.append(f"branch refs/heads/{branch}")
    elif not bare:
        lines.append("detached")
    return "\n".join(lines) + "\n\n"


def _porcelain(*entries: str) -> str:
    return "".join(entries)


CHORE = "chore/automated-upgrades-on"


def test_chore_worktree_passes_alone():
    p = _porcelain(_entry(SEAT, "master"), _entry(CHORE_WT, CHORE))
    ok, msg = assert_own_worktree(
        cwd=CHORE_WT, worktree_porcelain=p, current_branch=CHORE, staged_paths=[]
    )
    assert ok, msg


def test_chore_worktree_passes_with_other_tp_worktrees():
    p = _porcelain(
        _entry(SEAT, "master"), _entry(TP_WT, "tp/a"), _entry(CHORE_WT, CHORE)
    )
    ok, msg = assert_own_worktree(
        cwd=CHORE_WT, worktree_porcelain=p, current_branch=CHORE, staged_paths=[]
    )
    assert ok, msg


def test_master_seat_commit_not_blocked_by_chore_worktree():
    p = _porcelain(_entry(SEAT, "master"), _entry(CHORE_WT, CHORE))
    ok, msg = assert_own_worktree(
        cwd=SEAT, worktree_porcelain=p, current_branch="master", staged_paths=["x.py"]
    )
    assert ok, msg


def test_drifted_wt_worktree_still_blocks():
    cwd = "/home/user/repo-wt/b"
    allowed = []
    for drifted in [
        "candidate/x/single", "tp-attempt/x/1.1-abc", "tp/other", "master", "main"
    ]:
        p = _porcelain(
            _entry(SEAT, "master"), _entry(TP_WT, "tp/a"), _entry(cwd, drifted)
        )
        ok, msg = assert_own_worktree(
            cwd=cwd, worktree_porcelain=p,
            current_branch=drifted, staged_paths=[],
        )
        if ok:
            allowed.append(f"{cwd} was allowed (drifted onto {drifted!r}): {msg!r}")
    assert not allowed, "\n".join(allowed)


def test_sole_wt_worktree_drifted_to_master_blocks_bare_seat():
    cwd = "/home/user/repo-wt/a"
    p = _porcelain(_entry(SEAT, None, bare=True), _entry(cwd, "master"))
    ok, msg = assert_own_worktree(
        cwd=cwd, worktree_porcelain=p,
        current_branch="master", staged_paths=[],
    )
    assert not ok, f"{cwd} was allowed (sole -wt worktree on master, bare seat): {msg!r}"


def test_head_literal_in_wt_worktree_blocks():
    p = _porcelain(_entry(SEAT, "master"), _entry(TP_WT, "tp/a"))
    ok, msg = assert_own_worktree(
        cwd=TP_WT, worktree_porcelain=p, current_branch="HEAD", staged_paths=[]
    )
    assert not ok, f"{TP_WT} was allowed (detached HEAD literal): {msg!r}"


def test_main_detached_entry_without_branch_blocks():
    p = _porcelain(_entry(SEAT, "master"), _entry(TP_WT, None))
    buf = io.StringIO()
    with redirect_stderr(buf), patch(
        "worktree_isolation_guard._run_git", return_value="HEAD\n"
    ):
        rc = main(
            ["assert-own", "--cwd", TP_WT, "--worktree-porcelain", p, "--no-staged"]
        )
    assert rc == 1


def test_main_checkout_on_feature_branch_still_blocks():
    p = _porcelain(_entry(SEAT, "feature/x"), _entry(TP_WT, "tp/a"))
    ok, _ = assert_own_worktree(
        cwd=SEAT, worktree_porcelain=p, current_branch="feature/x", staged_paths=["x.py"]
    )
    assert not ok
