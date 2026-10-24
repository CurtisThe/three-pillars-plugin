#!/usr/bin/env python3
"""gc_design_leftovers — reap a merged design's leaked regress/rerun checkouts and branches.

Selects by branch only (never by path): `regress/<slug>` exactly and
`tp-rerun/<slug>-<8 hex>-<6 hex>`. Every worktree on such a branch is removed (dirty or locked
too, `--force --force`), then `git worktree prune`, then those branches (and any orphan branch of
the same patterns) are deleted. `foo-bar`'s branches are never matched by slug `foo`.
Dry-run by default; `--apply` acts. One JSON line, always exit 0 (a git failure sets `error`).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def matcher(slug: str):
    pat = re.compile(rf"(?:regress/{re.escape(slug)}|tp-rerun/{re.escape(slug)}-[0-9a-f]{{8}}-[0-9a-f]{{6}})")
    return lambda name: pat.fullmatch(name) is not None


def worktrees(repo: Path) -> list[tuple[str, str]]:
    """(path, branch) per registered worktree that is on a branch."""
    res = _git(repo, "worktree", "list", "--porcelain")
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or "git worktree list failed")
    rows, path = [], ""
    for line in res.stdout.splitlines() + [""]:
        if line.startswith("worktree "):
            path = line[9:]
        elif line.startswith("branch refs/heads/"):
            rows.append((path, line[len("branch refs/heads/"):]))
    return rows


def sweep(repo: Path, slug: str, apply: bool) -> dict:
    out: dict = {"slug": slug, "apply": apply, "worktrees": [], "branches": [], "errors": []}
    want = matcher(slug)
    try:
        wts = [(p, b) for p, b in worktrees(repo) if want(b)]
        res = _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/")
        if res.returncode != 0:
            raise RuntimeError(res.stderr.strip() or "git for-each-ref failed")
        heads = [b for b in res.stdout.split() if want(b)]
    except (RuntimeError, OSError) as exc:
        out["error"] = str(exc)
        return out
    out["worktrees"] = [p for p, _ in wts]
    out["branches"] = sorted(set(heads) | {b for _, b in wts})
    if not apply:
        return out
    for path, _ in wts:
        r = _git(repo, "worktree", "remove", "--force", "--force", path)
        if r.returncode != 0:
            out["errors"].append(f"remove {path}: {r.stderr.strip()}")
    _git(repo, "worktree", "prune")
    for b in out["branches"]:
        r = _git(repo, "branch", "-D", b)
        if r.returncode != 0:
            out["errors"].append(f"branch -D {b}: {r.stderr.strip()}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--slug", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--repo", default=".")
    args = ap.parse_args(argv)
    try:
        out = sweep(Path(args.repo), args.slug, args.apply)
    except Exception as exc:  # fail-open
        out = {"slug": args.slug, "apply": args.apply, "error": str(exc)}
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
