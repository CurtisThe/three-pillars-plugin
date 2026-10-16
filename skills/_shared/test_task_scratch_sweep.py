"""test_task_scratch_sweep.py — a killed re-run / red-at-base leaves nothing behind.

design: local-implement-and-review (impl-audit-1 #5)

The scratch ``finally`` never runs on SIGKILL; ``task_verify.py sweep`` removes this
slug's ``tp-rerun-*`` / ``tp-redbase-*`` worktrees and branches, and never another
slug's. Real tmp repos only (``attempt_fixture``).
"""
from __future__ import annotations

from pathlib import Path

import scratch_root
import task_scratch_sweep
from attempt_fixture import SLUG, branches, git, make_seat

RERUN = f"{SLUG}-0123abcd-a1b2c3"
REDBASE = f"{SLUG}-1.1-89abcdef"
OTHER = "other-0123abcd-d4e5f6"


def _leave(wt: Path, dirname: str, branch: str, parent: str = scratch_root.SCRATCH_DIR) -> Path:
    path = wt / parent / dirname
    path.parent.mkdir(parents=True, exist_ok=True)
    git(wt, "worktree", "add", "-q", "-b", branch, str(path), "HEAD")
    return path


def test_sweep_removes_this_slugs_scratch_only(tmp_path):
    _seat, wt = make_seat(tmp_path)
    rerun = _leave(wt, f"tp-rerun-{RERUN}", f"tp-rerun/{RERUN}")
    redbase = _leave(wt, f"tp-redbase-{REDBASE}", f"tp-redbase/{SLUG}/1.1-89abcdef")
    other = _leave(wt, f"tp-rerun-{OTHER}", f"tp-rerun/{OTHER}")
    orphan = wt / scratch_root.SCRATCH_DIR / f"tp-rerun-{SLUG}-fedcba98-000000"
    orphan.mkdir()  # a dir whose registration is already gone
    out = task_scratch_sweep.sweep(wt, SLUG)
    assert not rerun.exists() and not redbase.exists() and not orphan.exists()
    assert other.exists() and branches(wt, "tp-rerun/*") == [f"tp-rerun/{OTHER}"]
    assert branches(wt, "tp-redbase/*") == []
    assert sorted(out["branches"]) == [f"tp-redbase/{SLUG}/1.1-89abcdef",
                                       f"tp-rerun/{RERUN}"]
    assert len(out["worktrees"]) == 3
    assert str(rerun) not in git(wt, "worktree", "list")
    assert task_scratch_sweep.sweep(wt, SLUG) == {"worktrees": [], "branches": []}


def test_sweep_never_reads_a_prefix_sharing_slug_as_this_one(tmp_path):
    """impl-audit-2 #9: sweeping ``demo`` leaves ``demo-x``'s unregistered folders, and
    every red-at-base name (a task id with ``-`` included) is still this slug's."""
    import task_verify_red_base

    _seat, wt = make_seat(tmp_path)
    parent = wt / scratch_root.SCRATCH_DIR
    parent.mkdir(parents=True)
    foreign = [parent / f"tp-redbase-{SLUG}-x-1.1-89abcdef",  # slug demo-x, task 1.1
               parent / f"tp-redbase-{SLUG}-x-2_b.1-89abcdef"]
    own = parent / f"tp-redbase-{SLUG}-{task_verify_red_base.task_part('2-b.1')}-89abcdef"
    for path in (*foreign, own):
        path.mkdir()
    assert task_verify_red_base.task_part("2-b.1") == "2_b.1"
    out = task_scratch_sweep.sweep(wt, SLUG)
    assert all(p.exists() for p in foreign) and not own.exists()
    assert out["worktrees"] == [str(own)]


def test_sweep_clears_leftovers_under_either_scratch_parent(tmp_path):
    """Task 3.6: the sweep reads `scratch_root.scan_parents`, so a leftover of this slug
    under the legacy `.claude/worktrees/` parent is removed beside a new `.tp-scratch/`
    one. A legacy `tp-attempt-*` worktree is the attempt sweep's, never this one's."""
    _seat, wt = make_seat(tmp_path)
    new = _leave(wt, f"tp-rerun-{RERUN}", f"tp-rerun/{RERUN}")
    legacy = _leave(wt, f"tp-redbase-{REDBASE}", f"tp-redbase/{SLUG}/1.1-89abcdef",
                    parent=scratch_root.LEGACY_DIR)
    attempt = _leave(wt, "tp-attempt-demo-1.1-0a0b0c0d", "tp-attempt/demo/1.1-0a0b0c0d",
                     parent=scratch_root.LEGACY_DIR)
    out = task_scratch_sweep.sweep(wt, SLUG)
    assert not new.exists() and not legacy.exists()
    assert attempt.exists()  # owned by the attempt-record sweep, not by name
    assert sorted(out["worktrees"]) == sorted([str(new), str(legacy)])
    assert sorted(out["branches"]) == [f"tp-redbase/{SLUG}/1.1-89abcdef", f"tp-rerun/{RERUN}"]


def test_sweep_never_touches_a_same_named_dir_elsewhere(tmp_path):
    seat, wt = make_seat(tmp_path)
    elsewhere = tmp_path / f"tp-rerun-{RERUN}"
    git(seat, "worktree", "add", "-q", "-b", f"tp-rerun/{RERUN}", str(elsewhere), "HEAD")
    out = task_scratch_sweep.sweep(wt, SLUG)
    assert elsewhere.exists() and out["worktrees"] == []
    assert out["branches"] == []  # still checked out there: -D refuses
