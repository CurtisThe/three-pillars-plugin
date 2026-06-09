"""worktree_write_guard.py — the commit-time leak predicate.

Guards against the worktree-write-guard known issue (M7): a commit on the
default branch while tp/* worktrees are live that accidentally lands worktree
work (framework code or design artifacts) on the default branch.

The guard is fail-closed (parse success → enforce). The empty-staged-set case
exits 0 immediately — this is the no-commit / CI case (framework-check runs
with nothing staged and must never self-block).

Design refs:
  - three-pillars-docs/completed-tp-designs/worktree-write-guard/detailed-design.md
  - three-pillars-docs/completed-tp-designs/worktree-write-guard/plan.md
"""

from __future__ import annotations

import argparse
import subprocess
import sys

DEFAULT_BRANCHES = ("main", "master")

# Non-seed design-artifact basenames under tp-designs/<slug>/ that count as
# worktree work. A bare seed.md commit on the default branch is the legitimate
# seeding flow → never blocks.
DESIGN_ARTIFACTS = (
    "design.md",
    "detailed-design.md",
    "plan.md",
    "spike-results.md",
    "implementation-audit.md",
    "review.md",
    "lock.json",
    "decisions.md",
)

# Living-doc filenames under three-pillars-docs/ that are NOT guarded.
_LIVING_DOCS = frozenset({
    "vision.md",
    "architecture.md",
    "product_roadmap.md",
    "known_issues.md",
    "RELEASING.md",
})


def live_tp_worktrees(worktree_porcelain: str) -> list[str]:
    """Parse `git worktree list --porcelain`; return tp/<slug> branch names."""
    branches = []
    for line in worktree_porcelain.splitlines():
        line = line.strip()
        if line.startswith("branch "):
            ref = line[len("branch "):]
            prefix = "refs/heads/"
            if ref.startswith(prefix):
                name = ref[len(prefix):]
                if name.startswith("tp/"):
                    branches.append(name)
    return branches


def is_guarded_path(path: str) -> bool:
    """True iff `path` is worktree work that must not land on the default branch.

    Guarded:
      - tp-designs/<slug>/<DESIGN_ARTIFACTS> (NON-seed design artifacts), OR
      - skills/ or agents/ (framework code directories), OR
      - files ending in .py or .sh (framework code by extension).

    Not guarded:
      - tp-designs/<slug>/seed.md (seeds are not in DESIGN_ARTIFACTS)
      - three-pillars-docs/{vision,architecture,product_roadmap,known_issues,RELEASING}.md
      - completed-tp-designs/** (archived designs)
      - .claude-plugin/** version bumps (release files)
      - Root-level *.md docs (README.md, CLAUDE.md, etc.)
    """
    # Normalize separators
    p = path.replace("\\", "/")

    # Explicit exemptions first (fast path)
    # .claude-plugin/** → not guarded (release files)
    if p.startswith(".claude-plugin/"):
        return False

    # completed-tp-designs/** → not guarded
    if "completed-tp-designs/" in p:
        return False

    # Root-level *.md (no slash in path) → not guarded
    if p.endswith(".md") and "/" not in p:
        return False

    # three-pillars-docs/ top-level living docs → not guarded
    if p.startswith("three-pillars-docs/") and "/" not in p[len("three-pillars-docs/"):]:
        # e.g. three-pillars-docs/known_issues.md
        basename = p[len("three-pillars-docs/"):]
        if basename in _LIVING_DOCS:
            return False

    # tp-designs/<slug>/<name>: check if name is a DESIGN_ARTIFACT
    _TP_DESIGNS_PREFIX = "three-pillars-docs/tp-designs/"
    if p.startswith(_TP_DESIGNS_PREFIX):
        rest = p[len(_TP_DESIGNS_PREFIX):]
        parts = rest.split("/")
        # rest = <slug>/<name> (exactly 2 parts)
        if len(parts) == 2:
            slug, name = parts
            return name in DESIGN_ARTIFACTS
        # Deeper nesting → not a direct artifact → not guarded
        return False

    # Framework code: skills/ or agents/ directories
    if p.startswith("skills/") or p.startswith("agents/"):
        return True

    # Framework code: .py or .sh files anywhere (including root-level scripts)
    if p.endswith(".py") or p.endswith(".sh"):
        return True

    return False


def should_block(
    *,
    branch: str,
    staged_paths: list[str],
    worktree_porcelain: str,
) -> tuple[bool, str]:
    """The predicate. Block iff ALL of:
      (1) branch in DEFAULT_BRANCHES, AND
      (2) live_tp_worktrees(worktree_porcelain) is non-empty, AND
      (3) any(is_guarded_path(p) for p in staged_paths).

    Returns (blocked, guidance_message). When not blocked, (False, "").
    """
    if branch not in DEFAULT_BRANCHES:
        return False, ""

    live = live_tp_worktrees(worktree_porcelain)
    if not live:
        return False, ""

    if not any(is_guarded_path(p) for p in staged_paths):
        return False, ""

    live_str = ", ".join(live)
    msg = (
        f"FAIL: refusing to commit on the default branch '{branch}' while tp/* worktrees are live.\n"
        f"  This looks like worktree work leaking onto the default branch (known-issue M7).\n"
        f"  Live worktree(s): {live_str}\n"
        f"  Re-run inside the worktree:  cd ../<repo>-wt/<slug>  &&  <your command>\n"
        f"  (If this commit is genuinely default-branch work — a seed, /tp-docs-update, or a release —\n"
        f"   it should touch only seeds/living-docs/version files; split the worktree artifacts out.)"
    )
    return True, msg


def _run_git(repo: str, args: list[str]) -> str:
    """Run a git command in `repo` and return its stdout. Raises on error."""
    result = subprocess.run(
        ["git", "-C", repo] + args,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def main(argv=None) -> int:
    """CLI invoked by framework-check invariant #28.

    Override flags (for testing, no real git needed):
      --repo               repo root (default: cwd)
      --branch             override the current branch
      --staged-file        override staged files (repeatable)
      --no-staged          explicit empty staged set (hermetic; never reads git)
      --worktree-porcelain override the porcelain output (literal string)

    Exit 0 → no block. Exit 1 → blocked (guidance printed to stderr).
    Empty staged set → exit 0 immediately (no commit in progress). In override
    mode an explicit empty set is expressed via --no-staged, decoupled from the
    real `git diff --cached`; with no override flags the real index is read
    (live mode, exactly as framework-check.sh invokes it).
    """
    parser = argparse.ArgumentParser(
        description="Worktree write-guard: refuse default-branch commits of worktree work."
    )
    parser.add_argument("--repo", default=".", help="repo root (default: cwd)")
    parser.add_argument("--branch", default=None, help="override branch name")
    staged_group = parser.add_mutually_exclusive_group()
    staged_group.add_argument(
        "--staged-file",
        action="append",
        dest="staged_files",
        default=None,
        metavar="PATH",
        help="override staged files (repeatable); absent = read from git",
    )
    staged_group.add_argument(
        "--no-staged",
        action="store_true",
        dest="no_staged",
        default=False,
        help="override mode: explicit empty staged set (hermetic; never reads the git index)",
    )
    parser.add_argument(
        "--worktree-porcelain",
        default=None,
        dest="worktree_porcelain",
        help="override porcelain output (literal string)",
    )
    args = parser.parse_args(argv)

    repo = args.repo

    # Resolve branch
    if args.branch is not None:
        branch = args.branch
    else:
        branch = _run_git(repo, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()

    # Resolve staged paths
    if args.no_staged:
        # Explicit empty staged override — hermetic, never touches the real index.
        staged_paths = []
    elif args.staged_files is not None:
        staged_paths = args.staged_files
    else:
        raw = _run_git(repo, ["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
        staged_paths = [p for p in raw.splitlines() if p.strip()]

    # Empty staged set → no commit in progress → exit 0 immediately
    if not staged_paths:
        return 0

    # Resolve worktree porcelain
    if args.worktree_porcelain is not None:
        porcelain = args.worktree_porcelain
    else:
        porcelain = _run_git(repo, ["worktree", "list", "--porcelain"])

    blocked, msg = should_block(
        branch=branch,
        staged_paths=staged_paths,
        worktree_porcelain=porcelain,
    )
    if blocked:
        print(msg, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
