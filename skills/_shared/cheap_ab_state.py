#!/usr/bin/env python3
"""cheap_ab_state.py — the repo-wide state behind the cheap_ab.py harness.

design: none (just-do-it, PR #191 review r1, roadmap row "cheap-tier A/B runs").

- `worktree_roots(root)`: every worktree of the repo, so `budget` sees the in-flight
  rows of parallel design runs;
- `state_path` / `read_state` / `write_state`: the `alt-arm` pick counts, `{slot: n}` in
  `<git common dir>/ALT_STATE`. One file for every worktree, never tracked, so
  tp-post-merge step 6 reverting a row never loses a pick.

Every call fails open: outside git there is no state and one root. Stdlib-only.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import subprocess
import tempfile
from pathlib import Path

ALT_STATE = Path("three-pillars") / "cheap-ab-alt.json"


def git(root, *args) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def worktree_roots(root) -> list[Path]:
    """`root` plus every other non-bare worktree of its repo; just `root` outside git."""
    roots, bare, current = [Path(root).resolve()], False, None
    listing = git(root, "worktree", "list", "--porcelain") or ""
    for line in listing.splitlines() + [""]:
        if line.startswith("worktree "):
            current, bare = Path(line[len("worktree "):]), False
        elif line == "bare":
            bare = True
        elif not line and current is not None:
            try:
                if not bare and current.is_dir() and current.resolve() not in roots:
                    roots.append(current.resolve())
            except OSError:  # an unreadable parent: that worktree is skipped
                pass
            current = None
    return roots


def state_path(root) -> Path | None:
    common = (git(root, "rev-parse", "--git-common-dir") or "").strip()
    return (Path(root) / common / ALT_STATE).resolve() if common else None


def read_state(path: Path | None) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path else {}
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


@contextlib.contextmanager
def locked(path: Path | None):
    """Hold an exclusive flock on `<path>.lock` for one read-modify-write (fail-open:
    no path, a lock file that cannot open, or a filesystem without locks runs unlocked)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(f"{path}.lock", "a", encoding="utf-8")
    except (AttributeError, OSError):
        yield
        return
    with fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX)
        except OSError:
            pass
        yield


def write_state(path: Path, state: dict) -> None:
    tmp = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".alt.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, sort_keys=True)
        os.replace(tmp, path)
    except OSError:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)
