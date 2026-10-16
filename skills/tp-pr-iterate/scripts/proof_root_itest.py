"""proof_root_itest — temp repo helpers for the proof-root tests.

design: review-proof-out-of-tree (Tasks 1.1-1.6)

Test support only (no `test_` prefix, so pytest does not collect it): a main
checkout with one commit, a linked worktree of it, and a gitignore-blind tree
snapshot. Git runs through `loop_itest.git` (hermetic identity).
"""

from __future__ import annotations

import os
from pathlib import Path

import loop_itest

SUB = Path("three-pillars") / "review-proof"
LEGACY = Path(".three-pillars") / "review-proof"


def main_repo(tmp) -> Path:
    """A main checkout at `tmp/main` with one commit on `main`."""
    main = Path(tmp) / "main"
    main.mkdir()
    loop_itest.git(main, "init", "-q", "-b", "main")
    loop_itest.git(main, "config", "commit.gpgsign", "false")
    loop_itest.write(main, "a.txt", "a\n")
    loop_itest.git(main, "add", "a.txt")
    loop_itest.git(main, "commit", "-q", "-m", "base")
    return main


def linked(tmp) -> tuple[Path, Path]:
    """→ (main, wt): `tmp/wt` is a linked worktree of `tmp/main` on branch `side`."""
    main = main_repo(tmp)
    wt = Path(tmp) / "wt"
    loop_itest.git(main, "worktree", "add", "-q", "-b", "side", str(wt))
    return main, wt


def snapshot(*roots) -> set:
    """Every path under `roots` (dirs and files), for no-mutation assertions."""
    out = set()
    for root in roots:
        for d, dirs, files in os.walk(root):
            out.update(os.path.join(d, n) for n in dirs + files)
    return out
