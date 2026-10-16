#!/usr/bin/env python3
"""gc_agent_worktrees — reap landed `.claude/worktrees/agent-*` scratch worktrees.

A subagent spawned with worktree isolation gets a worktree under the MAIN checkout's
`.claude/worktrees/agent-<id>`, whichever linked worktree spawned it. Claude Code keeps that
worktree when the agent committed anything, and the design-worktree sweep (`gc_candidates`)
only looks inside `tp/*` worktrees, so these accumulate in the seat forever.

A worktree is removed only when every gate holds (each failure is a SKIP line, never an error):
  - clean: `git status --porcelain` is empty;
  - landed: its HEAD is an ancestor of `origin/<base>`, so no commit is lost;
  - old: nothing in it changed for `--min-age-h` hours (default 2), so a live agent's fresh
    worktree is never touched;
  - idle: no process of this user has its cwd at or under it.
Then `git worktree remove` (never `--force`) and, when the worktree had a branch that no other
worktree holds, `git branch -D` of that branch (its commits are on origin/<base>).
Dry-run by default; `--apply` removes. Fail-open: always exits 0. Stdlib only.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

PREFIX = "agent-"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def main_root(repo: Path) -> Path:
    """The main checkout: the parent of the shared git dir."""
    out = _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    return Path(out).parent


def agent_worktrees(root: Path) -> list[tuple[Path, str]]:
    """(path, branch-or-"") for each registered worktree under `<root>/.claude/worktrees/agent-*`."""
    scratch = (root / ".claude" / "worktrees").resolve()
    rows, path, branch = [], None, ""
    for line in _git(root, "worktree", "list", "--porcelain").stdout.splitlines() + [""]:
        if line.startswith("worktree "):
            path, branch = Path(line[9:]), ""
        elif line.startswith("branch refs/heads/"):
            branch = line[len("branch refs/heads/"):]
        elif not line and path is not None:
            if path.parent.resolve() == scratch and path.name.startswith(PREFIX):
                rows.append((path, branch))
            path = None
    return rows


def last_change(path: Path) -> float:
    """Newest mtime among the worktree dir, its index and its HEAD (gitdir side)."""
    stamps = [path.stat().st_mtime]
    gitdir = _git(path, "rev-parse", "--absolute-git-dir").stdout.strip()
    for name in ("index", "HEAD"):
        p = Path(gitdir) / name if gitdir else None
        if p is not None and p.exists():
            stamps.append(p.stat().st_mtime)
    return max(stamps)


def live_cwds() -> list[Path]:
    """The cwd of every process this user can read (others raise and are skipped)."""
    cwds = []
    for pid in os.listdir("/proc") if os.path.isdir("/proc") else []:
        if pid.isdigit():
            try:
                cwds.append(Path(os.readlink(f"/proc/{pid}/cwd")))
            except OSError:
                continue
    return cwds


def verdict(path: Path, base: str, min_age_s: float, cwds: list[Path], now: float) -> str:
    """"" when removable, else the SKIP reason."""
    if not path.is_dir():
        return "directory missing (run `git worktree prune`)"
    if _git(path, "status", "--porcelain").stdout.strip():
        return "uncommitted changes"
    if _git(path, "merge-base", "--is-ancestor", "HEAD", f"origin/{base}").returncode != 0:
        return f"HEAD not on origin/{base} (unlanded commits)"
    if now - last_change(path) < min_age_s:
        return "changed recently (a live agent may own it)"
    real = path.resolve()
    if any(c == real or real in c.parents for c in cwds):
        return "a process is working inside it"
    return ""


def sweep(repo: Path, base: str = "master", min_age_h: float = 2.0, apply: bool = False,
          cwds: list[Path] | None = None, now: float | None = None) -> list[Path]:
    """Print one REMOVE/SKIP line per agent worktree; return the removable (or removed) paths."""
    root = main_root(repo)
    if _git(root, "fetch", "--quiet", "origin").returncode != 0:
        print("warning: git fetch failed; using cached origin refs", file=sys.stderr)
    cwds = live_cwds() if cwds is None else cwds
    now = time.time() if now is None else now
    done = []
    for path, branch in agent_worktrees(root):
        why = verdict(path, base, min_age_h * 3600, cwds, now)
        if why:
            print(f"SKIP {path} — {why}")
            continue
        if not apply:
            print(f"REMOVE {path} — clean, landed on origin/{base}, idle")
            done.append(path)
            continue
        res = _git(root, "worktree", "remove", str(path))
        if res.returncode != 0:
            print(f"SKIP {path} — git worktree remove failed: {res.stderr.strip()}")
            continue
        note = ""
        if branch and _git(root, "branch", "-D", branch).returncode == 0:
            note = f"; deleted branch {branch}"
        print(f"REMOVED {path}{note}")
        done.append(path)
    return done


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=".")
    ap.add_argument("--base", default="master")
    ap.add_argument("--min-age-h", type=float, default=2.0)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    try:
        sweep(Path(args.repo), args.base, args.min_age_h, args.apply)
    except Exception as exc:  # fail-open: a sweep must never break its caller
        print(f"warning: gc_agent_worktrees failed: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
