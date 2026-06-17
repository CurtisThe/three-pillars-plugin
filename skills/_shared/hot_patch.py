#!/usr/bin/env python3
"""hot_patch.py — thin lane helper: worktree → trailered commit → PR → teardown.

Automates the hot-patch lane (design: hot-patch-protocol, Behavior 1):

  python3 "$TP_ROOT"/skills/_shared/hot_patch.py \\
      --trigger "fix teardown order" \\
      --slug teardown-order \\
      [--dry-run] \\
      [--repo-root <path>]

In --dry-run mode prints the command plan and exits (no git/gh executed).
In live mode (provision-and-instruct): executes 'git worktree add' to provision
the worktree, then prints the commit command, PR-create command, and teardown
guidance for the operator to run manually. gh is never invoked by this helper.

Pre-flight checks (run before provisioning):
  - Empty trigger → refuse
  - Trigger contains double-quote, backtick, $, backslash, !, or newline → refuse
  - --files list hits the exclusion tuple → VIOLATION + refuse
  - --estimated-lines exceeds 150 → VIOLATION + refuse

Merge guidance: operator runs 'gh pr merge --merge' (merge commit required).
Gate hooks always fire; bypassing them is gate-denied (Behavior 6).

Stdlib only (plus git at runtime for live mode).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants (duplicated from hot_patch_check.py to avoid circular import
# when this module is run as a subprocess; kept in sync by the test suite —
# see test_hot_patch.py::test_constants_sync)
# ---------------------------------------------------------------------------

DIFF_CAP = 150
LEDGER_RELPATH = "three-pillars-docs/tp-designs/orchestration/hot-patches.md"
WORKTREE_PREFIX = ".claude/worktrees/hot-patch-"
BRANCH_PREFIX = "hot-patch/"

# Exclusion tuple (must match hot_patch_check.py exactly)
EXCLUDED_PREFIXES = (
    ".three-pillars/",
)

EXCLUDED_FILES = frozenset({
    "framework-check.sh",
    "test-framework-check.sh",
    "skills/_shared/deterministic_gate.py",
    "skills/_shared/gate_roster.py",
    "skills/_shared/human_approval.py",
    "skills/_shared/file_size_guard.py",
    "skills/tp-merge/scripts/land.py",
    "skills/tp-merge-from-main/scripts/gate_cli.py",
    "skills/tp-merge-from-main/scripts/merge_gate.py",
    "skills/_shared/worktree_write_guard.py",
    "skills/_shared/worktree_isolation_guard.py",
    "skills/_shared/detect_unarchived.py",
    "skills/_shared/detect_orphan_locks.py",
    "skills/_shared/hot_patch_check.py",
    "skills/_shared/hot_patch.py",
    "skills/_shared/hot_patch_ledger.py",
    "skills/_shared/test_hot_patch_check.py",
    "skills/_shared/test_hot_patch_ledger.py",
    "skills/_shared/test_hot_patch_anomaly.py",
    "skills/_shared/test_hot_patch_nul_paths.py",
    "skills/_shared/test_hot_patch.py",
    "skills/_shared/test_hot_patch_stanza.py",
})


# ---------------------------------------------------------------------------
# Pre-flight predicates
# ---------------------------------------------------------------------------

def _violation(msg: str) -> str:
    return f"VIOLATION {msg}"


def preflight_files(files: list[str]) -> list[str]:
    """Return VIOLATION messages for any file hitting the exclusion tuple."""
    violations = []
    for f in files:
        f_norm = f.replace("\\", "/")
        if any(f_norm.startswith(p) for p in EXCLUDED_PREFIXES):
            violations.append(
                _violation(f"pre-flight exclusion: touches protected prefix '{f_norm}'")
            )
        elif f_norm in EXCLUDED_FILES:
            violations.append(
                _violation(f"pre-flight exclusion: touches protected file '{f_norm}'")
            )
    return violations


def preflight_lines(estimated_lines: int | None) -> list[str]:
    """Return VIOLATION if estimated_lines exceeds DIFF_CAP."""
    if estimated_lines is not None and estimated_lines > DIFF_CAP:
        return [
            _violation(
                f"pre-flight diff-cap: {estimated_lines} estimated lines exceeds "
                f"cap of {DIFF_CAP}"
            )
        ]
    return []


# ---------------------------------------------------------------------------
# Plan builder (pure — no side effects; testable in --dry-run)
# ---------------------------------------------------------------------------

def build_plan(
    trigger: str,
    slug: str,
    repo_root: str,
    files: list[str],
    estimated_lines: int | None,
) -> dict:
    """Build the hot-patch execution plan.

    Returns a dict with keys:
      ok: bool — False means pre-flight failed
      violations: list[str] — VIOLATION messages (if ok=False)
      steps: list[str] — ordered steps to execute (if ok=True)
      worktree_path: str
      branch: str
    """
    violations = preflight_files(files) + preflight_lines(estimated_lines)
    if violations:
        return {
            "ok": False,
            "violations": violations,
            "steps": [],
            "worktree_path": "",
            "branch": "",
        }

    worktree_path = f"{repo_root}/{WORKTREE_PREFIX}{slug}"
    branch = f"{BRANCH_PREFIX}{slug}"
    ledger_path = f"{worktree_path}/{LEDGER_RELPATH}"

    steps = [
        f"git worktree add -b {branch} {worktree_path}",
        f"# Stage your fix files in {worktree_path}",
        (
            f"# Append ledger entry to {ledger_path} — rides in the same commit "
            "(Behavior 2: paper arrives with the patch)"
        ),
        (
            f"git -C {worktree_path} commit "
            f'--trailer "hot-patch: {trigger}" '
            f"-m \"Hotfix: {trigger}\""
        ),
        f"gh pr create --base master --head {branch} --title \"Hotfix: {trigger}\"",
        (
            "# Operator merges: "
            "gh pr merge --merge <PR-NUMBER>  "
            "(merge commit required — squash would self-flag anomaly scan)"
        ),
        (
            f"git worktree remove {worktree_path} && "
            f"git branch -d {branch}"
        ),
    ]

    return {
        "ok": True,
        "violations": [],
        "steps": steps,
        "worktree_path": worktree_path,
        "branch": branch,
    }


def format_plan(plan: dict, trigger: str, slug: str) -> str:
    """Return human-readable plan text for --dry-run output."""
    lines = [
        f"=== Hot-patch dry-run plan: slug='{slug}' trigger='{trigger}' ===",
        "",
        "Steps (execute in order; operator merges the PR, teardown follows):",
        "",
    ]
    for i, step in enumerate(plan["steps"], 1):
        lines.append(f"  {i}. {step}")
    lines.append("")
    lines.append("Ledger: hot-patches.md append rides in the same commit as the fix.")
    lines.append(
        "Merge:  gh pr merge --merge <PR-NUMBER>  "
        "(merge commit; squash is out-of-protocol and self-flags the anomaly scan)"
    )
    lines.append(
        "Hooks:  full pre-commit battery fires on every commit in this worktree."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="hot_patch.py — hot-patch lane helper"
    )
    p.add_argument(
        "--trigger", required=True,
        help="Trigger description (required, non-empty); becomes the hot-patch: trailer value",
    )
    p.add_argument("--slug", required=True, help="Short slug for worktree/branch name")
    p.add_argument("--dry-run", action="store_true", help="Print plan; do not execute")
    p.add_argument("--repo-root", default=".", help="Path to the git repo root")
    p.add_argument(
        "--files", nargs="*", default=[],
        help="File paths to be staged (pre-flight exclusion check)",
    )
    p.add_argument(
        "--estimated-lines", type=int, default=None,
        help="Estimated diff size in lines (pre-flight cap check)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.trigger.strip():
        print("VIOLATION pre-flight: trigger must be non-empty", file=sys.stderr)
        return 1

    if re.search(r'["`$\\\n!]', args.trigger):
        print(
            "VIOLATION pre-flight: trigger must not contain double-quotes, backticks, "
            "dollar signs, backslashes, exclamation marks, or newlines "
            "(prevents shell injection in the suggested command)",
            file=sys.stderr,
        )
        return 1

    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", args.slug):
        print(
            f"VIOLATION pre-flight: slug {args.slug!r} is invalid — "
            "must match [a-z0-9][a-z0-9-]* (lowercase alphanumeric and hyphens only)",
            file=sys.stderr,
        )
        return 1

    repo_root = str(Path(args.repo_root).resolve())

    plan = build_plan(
        trigger=args.trigger,
        slug=args.slug,
        repo_root=repo_root,
        files=args.files or [],
        estimated_lines=args.estimated_lines,
    )

    if not plan["ok"]:
        for v in plan["violations"]:
            print(v, file=sys.stderr)
        return 1

    if args.dry_run:
        print(format_plan(plan, trigger=args.trigger, slug=args.slug))
        return 0

    # Live mode: execute the plan
    import subprocess  # noqa: PLC0415
    print(f"Provisioning worktree: {plan['worktree_path']}")
    result = subprocess.run(
        ["git", "-C", repo_root, "worktree", "add",
         "-b", plan["branch"], plan["worktree_path"]],
    )
    if result.returncode != 0:
        print("ERROR: worktree provisioning failed", file=sys.stderr)
        return 1

    ledger_abs = f"{plan['worktree_path']}/{LEDGER_RELPATH}"
    print(f"Worktree ready at {plan['worktree_path']} on branch {plan['branch']}")
    print(f"Stage your fix files, append ledger entry to {ledger_abs},")
    print(
        f"then commit: git -C {plan['worktree_path']} commit "
        f'--trailer "hot-patch: {args.trigger}" -m "Hotfix: {args.trigger}"'
    )
    print(f"Open PR: gh pr create --base master --head {plan['branch']}")
    print(
        f"After merge: git worktree remove {plan['worktree_path']} "
        f"&& git branch -d {plan['branch']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
