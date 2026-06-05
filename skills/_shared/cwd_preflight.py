"""cwd_preflight.py — fail-open cwd preflight for worktree-operating skills.

Checks whether the current working directory is inside the target tp/<design>
worktree. If a tp/<design> worktree exists but cwd is NOT inside it, the skill
is about to operate in the wrong checkout. Exit 3 with a cd-fix message so the
user can correct before any stray write occurs.

This is the ERGONOMIC early-refuse: fail-open on any ambiguity (git error,
unreadable worktree state). The commit-time guard (framework-check invariant #28)
is the fail-closed backstop.

Design refs:
  - three-pillars-docs/completed-tp-designs/worktree-write-guard/detailed-design.md
  - three-pillars-docs/completed-tp-designs/worktree-write-guard/plan.md

CLI usage (from SKILL.md preflight steps):
  python3 skills/_shared/cwd_preflight.py <design>
  → exit 0: ok (either cwd is inside the worktree, or no such worktree exists)
  → exit 3: refuse (worktree exists but cwd is outside it; cd fix printed to stderr)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def _safe_git(repo: str, args: list[str]) -> str | None:
    """Run git in `repo`; return stdout on success, None on any error (fail-open)."""
    try:
        result = subprocess.run(
            ["git", "-C", repo] + args,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
    except Exception:
        return None


def target_worktree_path(
    repo_root: str,
    design: str,
    *,
    worktree_porcelain: str | None = None,
) -> str | None:
    """Resolve the sibling worktree path for `design` from `git worktree list --porcelain`.

    Matches the worktree whose branch == tp/<design>. Returns its path, or None
    if no such worktree exists.

    Parameters
    ----------
    repo_root:
        Path to the main checkout (used only when worktree_porcelain is not provided).
    design:
        The design slug (without the tp/ prefix).
    worktree_porcelain:
        Literal porcelain output (for testing). If None, reads via subprocess.
    """
    if worktree_porcelain is None:
        porcelain = _safe_git(repo_root, ["worktree", "list", "--porcelain"])
        if porcelain is None:
            return None
    else:
        porcelain = worktree_porcelain

    target_branch = f"refs/heads/tp/{design}"
    current_worktree_path: str | None = None

    for line in porcelain.splitlines():
        line = line.strip()
        if line.startswith("worktree "):
            current_worktree_path = line[len("worktree "):]
        elif line.startswith("branch "):
            ref = line[len("branch "):]
            if ref == target_branch and current_worktree_path is not None:
                return current_worktree_path
        elif line == "":
            current_worktree_path = None

    return None


def check_cwd(
    *,
    cwd: str,
    design: str,
    repo_root: str,
    worktree_porcelain: str,
) -> tuple[bool, str]:
    """Returns (ok, message).

    ok=False (refuse) iff a tp/<design> worktree exists AND cwd is NOT inside it.
    ok=True when:
      - no tp/<design> worktree exists (nothing to redirect into), or
      - cwd is already inside the target worktree (the supported pattern).

    Message on refuse names the worktree path + the one-line `cd` fix.
    """
    target = target_worktree_path(repo_root, design, worktree_porcelain=worktree_porcelain)
    if target is None:
        # No tp/<design> worktree exists — normal single-checkout, nothing to do.
        return True, ""

    # Check if cwd is inside the target worktree (path-prefix containment).
    try:
        target_path = Path(os.path.realpath(target))
        cwd_path = Path(os.path.realpath(cwd))
        # cwd is inside target if target is a prefix of cwd
        try:
            cwd_path.relative_to(target_path)
            return True, ""  # cwd is inside (or equal to) the target worktree
        except ValueError:
            pass  # not a prefix → cwd is outside the worktree
    except Exception:
        return True, ""  # fail-open on path resolution error

    msg = (
        f"REFUSE: cwd is not inside the tp/{design} worktree.\n"
        f"  Target worktree: {target}\n"
        f"  Current cwd:     {cwd}\n"
        f"  Fix: cd {target}\n"
        f"  Then re-run your command from inside the worktree."
    )
    return False, msg


def main(argv=None) -> int:
    """CLI for the SKILL.md preflight step.

    Usage: python3 skills/_shared/cwd_preflight.py <design>
      --cwd <path>               override cwd (default: os.getcwd())
      --repo <path>              override repo root (default: cwd)
      --worktree-porcelain <str> override porcelain output (for testing)

    Exit 0: ok. Exit 3: refuse (message printed to stderr).
    Fail-open on any git error: exit 0 (never false-block a skill).
    """
    parser = argparse.ArgumentParser(
        description="cwd preflight: refuse if not inside the target tp/<design> worktree."
    )
    parser.add_argument("design", help="design slug (without tp/ prefix)")
    parser.add_argument("--cwd", default=None, help="override cwd (default: os.getcwd())")
    parser.add_argument("--repo", default=None, help="override repo root (default: cwd)")
    parser.add_argument(
        "--worktree-porcelain",
        default=None,
        dest="worktree_porcelain",
        help="override porcelain output (for testing)",
    )
    args = parser.parse_args(argv)

    # Resolve cwd
    cwd = args.cwd if args.cwd is not None else os.getcwd()
    repo_root = args.repo if args.repo is not None else cwd

    # Resolve worktree porcelain (fail-open on git error)
    if args.worktree_porcelain is not None:
        worktree_porcelain = args.worktree_porcelain
    else:
        result = _safe_git(repo_root, ["worktree", "list", "--porcelain"])
        if result is None:
            # Fail-open: can't read worktree state → don't block the skill
            return 0
        worktree_porcelain = result

    try:
        ok, msg = check_cwd(
            cwd=cwd,
            design=args.design,
            repo_root=repo_root,
            worktree_porcelain=worktree_porcelain,
        )
    except Exception:
        # Fail-open on any unexpected error in check_cwd
        return 0

    if not ok:
        print(msg, file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
