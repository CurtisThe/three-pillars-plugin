"""fixtures/delete_fence_repo.py — a real tp repo plus two linked `tp/<slug>` worktrees.

`build(tmp_path)` runs `git init` inside `tmp_path/repo`, makes one commit with
`three-pillars-docs/` present (so the activation markers are on disk, not
mocked), then adds two linked worktrees at `tmp_path/repo-wt/a` and
`tmp_path/repo-wt/b` on branches `tp/a` and `tp/b`. Everything lives under
pytest's `tmp_path`; nothing here deletes anything, and no fixture ever touches
a real worktree of this checkout.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def _git(args, cwd):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                          text=True, check=True).stdout


def build(tmp_path):
    """Returns `{"repo": …, "a": …, "b": …}` as strings."""
    tmp = Path(tmp_path)
    repo = tmp / "repo"
    repo.mkdir(parents=True)
    _git(["init", "-q", "-b", "master"], repo)
    _git(["config", "user.email", "fixture@example.invalid"], repo)
    _git(["config", "user.name", "Fixture"], repo)
    docs = repo / "three-pillars-docs"
    docs.mkdir()
    (docs / "vision.md").write_text("# Fixture vision\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "fixture: initial commit"], repo)
    out = {"repo": str(repo)}
    for slug in ("a", "b"):
        wt = tmp / "repo-wt" / slug
        wt.parent.mkdir(parents=True, exist_ok=True)
        # `-b` here, never `checkout -b` first: a branch already checked out in
        # the main checkout cannot be handed to a second worktree.
        _git(["worktree", "add", "-q", "-b", "tp/" + slug, str(wt)], repo)
        out[slug] = str(wt)
    return out
