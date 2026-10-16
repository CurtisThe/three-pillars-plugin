#!/usr/bin/env python3
"""scratch_worktree.py — throwaway worktrees under one literal root, no `cd`, no `$VAR` paths.

design: matchable-commands. Runs used to hand-build "compare against master" worktrees
(`~/t/master-check`, a `base-check` worktree under the legacy scratch parent) with
`$WT`-built paths and `--force` removes, none of which a permission rule can match. This helper
keeps every scratch worktree at `<repo>/.tp-scratch/scratch-<name>`, so one allow rule
covers add, run and remove (`python3 skills/_shared/scratch_worktree.py *`).

    scratch_worktree.py add <name> [<ref>]       detached worktree of <ref> (default HEAD); prints its path
    scratch_worktree.py run <name> -- <cmd…>     run <cmd…> inside it (cwd=, no `cd`); exits with its code
    scratch_worktree.py remove <name>            remove it; refuses any path outside the scratch root

Exit codes: 0 ok, 1 git failed, 64 refused (bad name, path outside the scratch root, root not
gitignored, worktree missing/unregistered). `run` exits with the command's own code (127 if it cannot start, 128+N if killed by signal N). Stdlib only.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# the module defines its own `scratch_root`, so the base module is aliased
import scratch_root as scratch_base  # noqa: E402 — the one scratch base

__all__ = ["main", "scratch_path", "Refused", "REFUSED"]

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
PREFIX = "scratch-"
REFUSED = 64


class Refused(Exception):
    """A request the helper will not act on (exit 64)."""


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def repo_root(cwd: Path) -> Path:
    r = _git(cwd, "rev-parse", "--show-toplevel")
    if r.returncode != 0:
        raise Refused("not inside a git work tree")
    return Path(r.stdout.strip()).resolve()


def scratch_root(root: Path) -> Path:
    return root / scratch_base.SCRATCH_DIR


def scratch_path(root: Path, name: str) -> Path:
    """`<root>/.tp-scratch/scratch-<name>`; refuses a name that could escape that root."""
    if not NAME_RE.match(name):
        raise Refused(f"bad name {name!r}: use [a-z0-9][a-z0-9-]* (no '/', '..' or absolute paths)")
    path = scratch_root(root) / f"{PREFIX}{name}"
    if path.resolve().parent != scratch_root(root).resolve():
        raise Refused(f"{path} is outside the scratch root {scratch_root(root)}")
    return path


def _registered(root: Path, path: Path) -> bool:
    r = _git(root, "worktree", "list", "--porcelain")
    return any(line == f"worktree {path.resolve()}" for line in r.stdout.splitlines())


def cmd_add(root: Path, name: str, ref: str) -> int:
    path = scratch_path(root, name)
    if ref.startswith("-"):
        raise Refused(f"bad ref {ref!r}: a ref may not start with '-'")
    scratch_base.ensure_excluded(root)  # fail-open: a consumer repo has no `.gitignore` line
    if _git(root, "check-ignore", "-q", str(path)).returncode != 0:
        raise Refused(f"{scratch_root(root)} is not gitignored; add "
                      f"`{scratch_base.ignore_line()}` to .gitignore")
    if path.exists():
        raise Refused(f"{path} already exists; remove it first")
    r = _git(root, "worktree", "add", "-q", "--detach", str(path), ref)
    if r.returncode != 0:
        print(f"scratch_worktree: git worktree add failed: {r.stderr.strip()}", file=sys.stderr)
        return 1
    print(path)
    return 0


def cmd_run(root: Path, name: str, argv: list[str]) -> int:
    path = scratch_path(root, name)
    if not argv:
        raise Refused("run needs a command after `--`")
    if not _registered(root, path):
        raise Refused(f"{path} is not a registered worktree; run `add {name}` first")
    try:
        code = subprocess.run(argv, cwd=path).returncode
    except OSError as exc:
        print(f"scratch_worktree: cannot run {argv[0]!r}: {exc}", file=sys.stderr)
        return 127
    return 128 - code if code < 0 else code  # killed by signal N -> 128+N, as a shell reports it


def cmd_remove(root: Path, name: str) -> int:
    path = scratch_path(root, name)
    if not _registered(root, path):
        if path.exists():
            raise Refused(f"{path} exists but is not a registered worktree; not touching it")
        print(f"scratch_worktree: {path} not present")
        return 0
    r = _git(root, "worktree", "remove", "--force", str(path))
    if r.returncode != 0:
        print(f"scratch_worktree: git worktree remove failed: {r.stderr.strip()}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None, cwd: Path | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd_tail: list[str] = []
    if "--" in argv:
        i = argv.index("--")
        argv, cmd_tail = argv[:i], argv[i + 1:]
    ap = argparse.ArgumentParser(prog="scratch_worktree.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add", help="create the scratch worktree (detached)")
    add.add_argument("name")
    add.add_argument("ref", nargs="?", default="HEAD")
    run = sub.add_parser("run", help="run a command inside it: run <name> -- <cmd…>")
    run.add_argument("name")
    rm = sub.add_parser("remove", help="remove the scratch worktree")
    rm.add_argument("name")
    args = ap.parse_args(argv)
    try:
        root = repo_root(cwd or Path.cwd())
        if args.cmd == "add":
            return cmd_add(root, args.name, args.ref)
        if args.cmd == "run":
            return cmd_run(root, args.name, cmd_tail)
        return cmd_remove(root, args.name)
    except Refused as exc:
        print(f"scratch_worktree: refused: {exc}", file=sys.stderr)
        return REFUSED


if __name__ == "__main__":
    sys.exit(main())
