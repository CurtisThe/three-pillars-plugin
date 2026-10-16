"""Stale-index guard: the second clause of the orchestrator's assert-before-commit rule.

design: orchestrator-index-staleness-guard

Assert-before-commit checks the *branch*. After a fold, an ff-merge, a ``git stash pop`` or a
``--no-commit`` cherry-pick/revert moves ``HEAD`` under a populated index, the branch is right
but the index can still hold the pre-move content, and committing it silently reverts the
move (a review fix, say) under a message that claims the opposite.

The check is operation-agnostic: before the orchestrator stages its own work after any such
operation, ``git diff --cached HEAD`` must be empty. Non-empty means stop and show the staged
diff to the operator. ``verify-discard`` lets a dirty index be reset only after proving its
content is byte-identical to a named commit, so a reset never destroys unsaved work.

CLI (``-C DIR`` selects the repo, default the current directory):
    index_guard.py check                       exit 0 clean / 1 stale (staged diff printed) / 2 git error
    index_guard.py verify-discard --ref REF [--reset]
                                               exit 0 index == REF (and reset to HEAD with --reset)
                                               / 1 differs, nothing touched / 2 git error
"""
from __future__ import annotations

import argparse
import subprocess
import sys


class GitError(RuntimeError):
    """A git call failed for a reason other than 'there is a diff'."""


def _git(repo, *args, ok=(0,)) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
        )
    except OSError as exc:
        raise GitError(f"git not runnable: {exc}") from exc
    if proc.returncode not in ok:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.returncode}")
    return proc


def staged_vs(repo, ref="HEAD") -> str:
    """``--name-status`` of the index against ``ref``; empty string when identical."""
    return _git(repo, "diff", "--cached", "--no-renames", "--name-status", ref).stdout


def is_clean(repo) -> bool:
    """True when the index holds exactly ``HEAD``'s content."""
    return not staged_vs(repo, "HEAD").strip()


def identical_to(repo, ref) -> bool:
    """True when the staged content is byte-identical to the tree of ``ref``."""
    _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    return not staged_vs(repo, ref).strip()


def reset_index(repo) -> None:
    """Mixed reset to HEAD: the index follows HEAD, the working tree is untouched."""
    _git(repo, "reset", "-q", "HEAD")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="index_guard.py")
    parser.add_argument("-C", dest="repo", default=".", help="repository directory")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="refuse when the index differs from HEAD")
    vd = sub.add_parser("verify-discard", help="prove the index equals REF before discarding it")
    vd.add_argument("--ref", required=True, help="commit the staged content must equal")
    vd.add_argument("--reset", action="store_true", help="reset the index to HEAD when proven")
    args = parser.parse_args(argv)

    try:
        if args.command == "check":
            diff = staged_vs(args.repo, "HEAD")
            if not diff.strip():
                print("index-guard: clean (index == HEAD)")
                return 0
            print("index-guard: STALE INDEX — staged content differs from HEAD; stop and show the operator:")
            print(diff.rstrip())
            return 1
        if identical_to(args.repo, args.ref):
            print(f"index-guard: staged content is byte-identical to {args.ref}")
            if args.reset:
                reset_index(args.repo)
                print("index-guard: index reset to HEAD")
            return 0
        print(f"index-guard: staged content differs from {args.ref}; nothing reset (may hold unsaved work)")
        print(staged_vs(args.repo, args.ref).rstrip())
        return 1
    except GitError as exc:
        print(f"index-guard: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
