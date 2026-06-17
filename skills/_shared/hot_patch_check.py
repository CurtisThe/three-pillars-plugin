#!/usr/bin/env python3
"""hot_patch_check.py — invariant #37 predicate for the hot-patch lane.

Called by framework-check.sh stanza #37. Emits machine-greppable VIOLATION
lines on stdout and exits 1 if any finding is present; exits 0 when clean.
Exit 2 signals an internal error (crash or git plumbing failure).

Checks (a) ledger coverage deadline, (b) exclusion + diff-cap on every
trailered commit on the default branch, (c) post-baseline anomaly scan for
unsanctioned non-merge master commits touching framework paths.

Ledger, anomaly, and deadline logic live in hot_patch_ledger.py (split for
the 500-line cap). This module owns the CLI and exclusion/diff-cap checks.

The scan-cost note: arm (c) uses --since-as-filter (full-history traversal,
no cut-off at baseline), which is still cheap at the observed hot-patch rate
and master history scale. Re-evaluate if master grows beyond ~10k commits.

Stdlib only.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Ensure repo root is on sys.path so "skills._shared.hot_patch_ledger" resolves
# when this file is invoked as a script (python3 skills/_shared/hot_patch_check.py)
# AND as a module (python3 -m pytest / importlib).
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from skills._shared.hot_patch_ledger import (  # noqa: E402
    LEDGER_RELPATH,
    _trailered_commits_on_head,
    check_anomaly,
    check_ledger_coverage,
    parse_ledger,   # re-exported for backward compat with existing tests
    _sha_covered,   # re-exported for backward compat
)

# ---------------------------------------------------------------------------
# Constants (kept in sync with hot_patch.py by the test suite)
# ---------------------------------------------------------------------------

DIFF_CAP = 150  # max changed lines (adds+dels) per hot-patch commit

# Paths that a trailered hot-patch commit may NEVER touch (moral-hazard bound)
EXCLUDED_PREFIXES = (
    ".three-pillars/",  # covers file-size-grandfather.txt + gate config
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
    # Lane's own modules — cannot self-modify (Behavior 4)
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
# Git helpers
# ---------------------------------------------------------------------------

def _git(args: list[str], repo: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command in repo; return the CompletedProcess."""
    return subprocess.run(
        ["git", "-C", repo] + args,
        capture_output=True,
        text=True,
        check=check,
    )


def _commit_files(sha: str, repo: str) -> list[str]:
    """Return list of file paths changed in sha (--name-only, --no-renames).

    -z emits NUL-separated paths; git never C-quotes paths in -z mode so
    non-ASCII and special-character paths arrive verbatim, making prefix
    matching against EXCLUDED_PREFIXES unconditionally correct.
    """
    result = _git(
        ["show", "--name-only", "--no-renames", "-z", "--format=", sha],
        repo,
    )
    # NUL-delimited output: split on NUL, drop genuinely empty tokens (leading
    # NUL from the empty --format= header, trailing NUL after the last path).
    # Do NOT strip() — a filename consisting entirely of spaces is a valid path
    # and must not be silently discarded.
    # Backslash normalization retained: Linux allows literal backslash in
    # filenames; normalise so callers need not handle both separators.
    paths = result.stdout.split("\0")
    return [p.replace("\\", "/") for p in paths if p]


def _numstat(sha: str, repo: str) -> list[tuple[int | None, int | None, str]]:
    """Return (added, deleted, path) tuples from git show --numstat for sha.

    --no-renames ensures renames surface as delete+add of real paths so
    both the source and destination are separately checked.
    -z emits NUL-terminated records (adds\\tdels\\tpath\\0); git never C-quotes
    paths in -z mode, so special-character paths arrive verbatim.
    """
    result = _git(
        ["show", "--numstat", "--no-renames", "-z", "--format=", sha],
        repo,
    )
    rows: list[tuple[int | None, int | None, str]] = []
    # Each record is "adds\tdels\tpath" terminated by NUL; split on NUL.
    # Do NOT strip() records — in -z mode only genuinely empty tokens occur
    # (the leading blank from --format= and the trailing blank after the last
    # NUL), so filtering with `if not record` is sufficient and safe.
    for record in result.stdout.split("\0"):
        if not record:
            continue
        parts = record.split("\t", 2)
        if len(parts) < 3:
            continue
        added_s, deleted_s, path = parts
        # Backslash normalization is intentionally deferred to check_diff_cap so
        # that the LEDGER_RELPATH exemption can compare the RAW path (pre-normalization).
        # A file literally named with backslashes (e.g. "three-pillars-docs\tp-designs\…")
        # must NOT be exempted — only the byte-identical LEDGER_RELPATH is exempt.
        # Binary files show "-" for both counts
        if added_s == "-" or deleted_s == "-":
            rows.append((None, None, path))
        else:
            try:
                rows.append((int(added_s), int(deleted_s), path))
            except ValueError:
                rows.append((None, None, path))
    return rows


# ---------------------------------------------------------------------------
# Exported predicates
# ---------------------------------------------------------------------------

def check_exclusions(sha: str, repo: str) -> list[str]:
    """Return VIOLATION messages if sha touches excluded paths; empty list if clean."""
    files = _commit_files(sha, repo)
    violations = []
    for f in files:
        f_norm = f.replace("\\", "/")
        if any(f_norm.startswith(p) for p in EXCLUDED_PREFIXES):
            violations.append(
                f"VIOLATION {sha[:12]} exclusion: touches protected prefix '{f_norm}'"
            )
        elif f_norm in EXCLUDED_FILES:
            violations.append(
                f"VIOLATION {sha[:12]} exclusion: touches protected file '{f_norm}'"
            )
    return violations


def check_diff_cap(sha: str, repo: str) -> list[str]:
    """Return VIOLATION messages if sha exceeds DIFF_CAP; empty list if clean.

    hot-patches.md is excluded from the sum (paper never eats the fix budget).
    Binary files (None counts) fail outright.
    """
    rows = _numstat(sha, repo)
    total = 0
    for added, deleted, path in rows:
        # Exemption uses the RAW pre-normalization path so that a file literally
        # named with backslashes (e.g. "three-pillars-docs\tp-designs\…\hot-patches.md")
        # is NOT accidentally exempted after normalization.  Only a path that is
        # byte-identical to LEDGER_RELPATH (forward slashes, no padding) is exempt.
        if path == LEDGER_RELPATH:
            continue  # paper is exempt
        # Normalize backslashes to forward slashes for display and prefix matching
        # (fail-closed: normalization may merge distinct raw paths, but that is the
        # conservative direction — it cannot cause a real violation to be missed).
        path_norm = path.replace("\\", "/")
        if added is None or deleted is None:
            return [
                f"VIOLATION {sha[:12]} diff-cap: binary file '{path_norm}' — "
                "binary files are not permitted in hot-patch commits"
            ]
        total += added + deleted
    if total > DIFF_CAP:
        return [
            f"VIOLATION {sha[:12]} diff-cap: {total} changed lines exceeds cap of {DIFF_CAP}"
        ]
    return []


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="hot_patch_check — invariant #37 predicate"
    )
    p.add_argument("--repo-root", default=".", help="Path to the git repo root")
    p.add_argument(
        "--check-sha", metavar="SHA",
        help="Check a specific trailered commit for exclusion + diff-cap violations "
             "(pre-flight mode; does NOT run the full stanza scan)",
    )
    p.add_argument(
        "--ledger-file", metavar="PATH",
        help="Path to hot-patches.md (defaults to REPO_ROOT/LEDGER_RELPATH)",
    )
    p.add_argument(
        "--now", metavar="ISO8601",
        help="Override 'now' for ledger deadline checks (for testing)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """Run all checks; return exit code (0 = clean, 1 = violations, 2 = error)."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    repo = str(Path(args.repo_root).resolve())

    try:
        return _run_checks(args, repo)
    except Exception as exc:  # noqa: BLE001
        print(f"hot_patch_check: internal error: {exc}", file=sys.stderr)
        return 2


def _run_checks(args: argparse.Namespace, repo: str) -> int:
    """Execute all checks and return exit code."""
    violations: list[str] = []

    if args.check_sha:
        # Pre-flight mode: check a single commit for exclusion + diff-cap only
        violations.extend(check_exclusions(sha=args.check_sha, repo=repo))
        violations.extend(check_diff_cap(sha=args.check_sha, repo=repo))
    else:
        # Full stanza mode: run arm (b) on all trailered commits (FULL history —
        # not just post-baseline; pre-baseline trailered commits are also checked).
        # Only arm (c) is baseline-scoped. Arms (a)/(b) sweep everything.

        # Arm (b): exclusion + diff-cap on every trailered commit on the default branch
        trailered = _trailered_commits_on_head(repo)
        for sha in trailered:
            violations.extend(check_exclusions(sha=sha, repo=repo))
            violations.extend(check_diff_cap(sha=sha, repo=repo))

        # Arm (a): ledger coverage deadline
        ledger_path = (
            Path(args.ledger_file) if args.ledger_file else Path(repo) / LEDGER_RELPATH
        )
        if ledger_path.exists():
            ledger_text = ledger_path.read_text()
        else:
            # Missing ledger: treat as empty (obligations accrue normally)
            ledger_text = ""
            # If any trailered commits exist, emit an immediate violation
            if trailered:
                violations.append(
                    "VIOLATION ledger-missing: hot-patches.md not found but trailered "
                    "commits exist on the default branch"
                )
        violations.extend(
            check_ledger_coverage(repo=repo, ledger_text=ledger_text, now_iso=args.now)
        )

        # Arm (c): anomaly scan (post-baseline non-merge master commits)
        violations.extend(check_anomaly(repo=repo))

    for v in violations:
        print(v)

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
