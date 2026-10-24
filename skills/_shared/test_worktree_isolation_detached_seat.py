"""A detached bare seat is not carved out; a branchless or master bare seat is.

Hermetic: worktree-list porcelain strings only, no git call.
"""

from __future__ import annotations

from worktree_isolation_guard import assert_own_worktree

SEAT = "/home/user/repo"
TP_WT = "/home/user/repo-wt/a"
STAGED = ["three-pillars-docs/tp-designs/orchestration/handoff.md"]


def _entry(path: str, branch: str | None, bare: bool = False) -> str:
    lines = [f"worktree {path}", "HEAD abc123"]
    if bare:
        lines.append("bare")
    if branch:
        lines.append(f"branch refs/heads/{branch}")
    elif not bare:
        lines.append("detached")
    return "\n".join(lines) + "\n\n"


def _check(current_branch: str):
    p = _entry(SEAT, None, bare=True) + _entry(TP_WT, "tp/a")
    return assert_own_worktree(
        cwd=SEAT, worktree_porcelain=p, current_branch=current_branch,
        staged_paths=STAGED,
    )


def test_detached_head_bare_seat_is_refused():
    ok, msg = _check("HEAD")
    assert ok is False
    assert SEAT in msg


def test_branchless_bare_seat_keeps_carve_out():
    ok, msg = _check("")
    assert ok is True, msg


def test_master_bare_seat_keeps_carve_out():
    ok, msg = _check("master")
    assert ok is True, msg
