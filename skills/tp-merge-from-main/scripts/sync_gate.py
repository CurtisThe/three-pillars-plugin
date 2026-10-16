"""sync_gate.py — push-readiness gate of a base-sync (`/tp-merge-from-main` step 6.7).

Checks only what a base-sync can decide before it pushes, on the local worktree:

  merge-concluded      no unmerged index entries and no merge, rebase, cherry-pick or revert
                       in progress
  tracked-tree-clean   no staged or unstaged change to a tracked file, so the pushed head
                       is the tree that was tested and committed (untracked files are ignored)
  base-is-ancestor     `git merge-base --is-ancestor <base> HEAD` — the local fact that clears
                       the remote `mergeable` once pushed
  no-leftover-markers  M = the newest first-parent merge commit at or below HEAD. For every file
                       HEAD changed relative to BOTH of M's parents, HEAD's raw blob may not hold
                       more `<<<<<<<` / `>>>>>>>` lines (then a space or end of line) than either
                       parent's blob: a real leftover marker is in neither parent, a quoted one
                       came from a side. Raw blobs, not a diff, so .gitattributes binary/-diff,
                       textconv and diff config cannot hide a file. `=======` / `|||||||` are not
                       checked: valid markdown (setext underline, empty table row). N/A when no
                       merge commit is on HEAD's first-parent line.

The land predicates (mergeable, approval, review proof, checks, stamps) describe the remote
head and cannot hold before this push; they are enforced by `/tp-merge`, and step 7a prints
them as an advisory readout after the push.

Exit codes: 0 = PASS, 1 = FAIL (a check failed), 2 = could not run (usage error, not a git
repo, base ref unresolvable, git error). 2 refuses the push like 1 (fail-closed).
LABEL is printed on every path.

Usage:
  python3 skills/tp-merge-from-main/scripts/sync_gate.py --repo <path> --base <ref>

stdlib + git only; no gh, no network.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

LABEL = "sync gate — push-readiness of a base-sync only; landing is gated by /tp-merge"

_MARKER = re.compile(r"^(<{7}|>{7})( |$)")
_IN_PROGRESS_REFS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "REBASE_HEAD")


class GateError(Exception):
    """git could not answer a required question; the gate cannot run (exit 2)."""


@dataclass(frozen=True)
class Check:
    name: str
    status: str  # "PASS" | "FAIL" | "N/A"
    detail: str


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False,
        )
    except OSError as e:
        raise GateError(f"git not runnable: {e}") from e


def _git_out(repo: Path, *args: str) -> str:
    r = _git(repo, *args)
    if r.returncode != 0:
        raise GateError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def _merge_concluded(repo: Path) -> Check:
    unmerged = sorted({ln.split("\t", 1)[-1] for ln in _git_out(repo, "ls-files", "-u").splitlines()})
    in_progress = [op for op in _IN_PROGRESS_REFS
                   if _git(repo, "rev-parse", "-q", "--verify", op).returncode == 0]
    for d in ("rebase-merge", "rebase-apply"):
        if Path(repo, _git_out(repo, "rev-parse", "--git-path", d).strip()).exists():
            in_progress.append(d)
    if unmerged or in_progress:
        parts = []
        if unmerged:
            parts.append(f"unmerged: {', '.join(unmerged)}")
        if in_progress:
            parts.append(f"operation in progress ({', '.join(in_progress)}) — finish it first")
        return Check("merge-concluded", "FAIL", "; ".join(parts))
    return Check("merge-concluded", "PASS", "no unmerged paths, no merge in progress")


def _tracked_tree_clean(repo: Path) -> Check:
    dirty = _git_out(repo, "status", "--porcelain", "--untracked-files=no").splitlines()
    if dirty:
        paths = ", ".join(ln[3:] for ln in dirty[:10])
        return Check("tracked-tree-clean", "FAIL", f"uncommitted tracked changes: {paths}")
    return Check("tracked-tree-clean", "PASS", "no uncommitted tracked changes")


def _base_is_ancestor(repo: Path, base: str) -> Check:
    r = _git(repo, "merge-base", "--is-ancestor", base, "HEAD")
    if r.returncode == 0:
        return Check("base-is-ancestor", "PASS", f"{base} is an ancestor of HEAD")
    if r.returncode == 1:
        return Check("base-is-ancestor", "FAIL", f"{base} is not an ancestor of HEAD — merge it in")
    raise GateError(f"git merge-base --is-ancestor failed: {r.stderr.strip()}")


def _blob_markers(repo: Path, rev: str, path: str) -> Counter:
    """Marker-shaped lines in the raw blob `rev:path` (empty when the path is absent there)."""
    r = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "blob", f"{rev}:{path}"],
        capture_output=True, check=False,
    )
    if r.returncode != 0:
        return Counter()
    text = r.stdout.decode("utf-8", errors="replace")
    return Counter(ln for ln in text.splitlines() if _MARKER.match(ln))


def _changed(repo: Path, rev: str) -> set[str]:
    out = _git_out(repo, "diff", "--name-only", "-z", "--no-renames", rev, "HEAD")
    return {p for p in out.split("\0") if p}


def _no_leftover_markers(repo: Path) -> Check:
    merge = _git_out(repo, "rev-list", "--first-parent", "--merges", "-n", "1", "HEAD").strip()
    if not merge:
        return Check("no-leftover-markers", "N/A", "no merge commit on HEAD's first-parent line")
    p1, p2 = f"{merge}^1", f"{merge}^2"
    left = []
    for path in sorted(_changed(repo, p1) & _changed(repo, p2)):
        head = _blob_markers(repo, "HEAD", path)
        base = _blob_markers(repo, p1, path) | _blob_markers(repo, p2, path)
        if head - base:
            left.append(path)
    if left:
        return Check("no-leftover-markers", "FAIL", f"conflict markers committed in: {', '.join(left)}")
    return Check("no-leftover-markers", "PASS", f"no conflict markers left by merge {merge[:12]}")


def run_checks(repo: Path, base: str) -> list[Check]:
    """Run every check; raise GateError when the gate cannot run."""
    repo = Path(repo)
    if _git(repo, "rev-parse", "--is-inside-work-tree").returncode != 0:
        raise GateError(f"{repo} is not a git worktree")
    if _git(repo, "rev-parse", "-q", "--verify", f"{base}^{{commit}}").returncode != 0:
        raise GateError(f"base ref {base!r} does not resolve to a commit — fetch it first")
    return [
        _merge_concluded(repo),
        _tracked_tree_clean(repo),
        _base_is_ancestor(repo, base),
        _no_leftover_markers(repo),
    ]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="sync_gate.py", description=LABEL)
    parser.add_argument("--repo", required=True, help="the design worktree to check")
    parser.add_argument("--base", required=True, help="the base ref merged in, e.g. origin/master")
    print(f"GATE: {LABEL}")
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        if e.code == 0:  # --help
            return 0
        print("VERDICT: COULD-NOT-RUN (usage error)")
        return 2
    try:
        checks = run_checks(Path(args.repo), args.base)
    except GateError as e:
        print(f"VERDICT: COULD-NOT-RUN — {e}")
        return 2
    failed = [c for c in checks if c.status == "FAIL"]
    print(f"VERDICT: {'FAIL' if failed else 'PASS'}")
    for c in checks:
        print(f"  [{c.status}] {c.name} — {c.detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
