#!/usr/bin/env python3
"""hot_patch_check.py — invariant #37 predicate for the hot-patch lane.

Called by the commit guard's `commit-msg` hook and (dev-repo only) framework-check.sh
stanza #37. Emits machine-greppable VIOLATION
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
    union_ledger_text,
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
    "scripts/fc-selftest/",  # self-test cases moved out of test-framework-check.sh
)

EXCLUDED_FILES = frozenset({
    "framework-check.sh",
    "test-framework-check.sh",
    "skills/_shared/deterministic_gate.py",
    "skills/_shared/gate_roster.py",
    "skills/_shared/human_approval.py",
    "skills/_shared/file_size_guard.py",
    "skills/_shared/low_doc_parts.py",
    "skills/tp-merge/scripts/land.py",
    "skills/tp-merge-from-main/scripts/gate_cli.py",
    "skills/tp-merge-from-main/scripts/merge_gate.py",
    "skills/_shared/worktree_write_guard.py",
    "skills/_shared/worktree_isolation_guard.py",
    "skills/_shared/scratch_root.py",
    "skills/_shared/detect_unarchived.py",
    "skills/_shared/detect_orphan_locks.py",
    # Lane's own modules — cannot self-modify (Behavior 4)
    "skills/_shared/hot_patch_check.py",
    "skills/_shared/hot_patch.py",
    "skills/_shared/hot_patch_ledger.py",
    "skills/_shared/hot_patch_hook.py",
    "skills/_shared/test_hot_patch_check.py",
    "skills/_shared/test_hot_patch_ledger.py",
    "skills/_shared/test_hot_patch_ledger_base.py",
    "skills/_shared/test_hot_patch_anomaly.py",
    "skills/_shared/test_hot_patch_nul_paths.py",
    "skills/_shared/test_hot_patch.py",
    "skills/_shared/test_hot_patch_stanza.py",
    "skills/_shared/test_hot_patch_ledger_union.py",
    "skills/_shared/test_hot_patch_refs.py",
    "skills/_shared/test_hot_patch_commit_msg.py",
    "skills/_shared/test_hot_patch_branch.py",
    "skills/_shared/test_hot_patch_discharge.py",
    "skills/_shared/test_hot_patch_excluded_closure.py",
    # The lane cannot edit its own guard (consumer-repo-parity Task 5.7):
    # commit_guard.py's own transitive import closure within skills/_shared/,
    # the guard-adjacent modules the design names by hand (some of which the
    # closure walk does not reach, e.g. ci_gate_run.py / ci_local_stamp.py),
    # the sentinel body, and every one of their on-disk tests.
    "skills/_shared/commit_guard.py",
    "skills/_shared/commit_guard_settings.py",
    "skills/_shared/commit_guard_hooks.py",
    "skills/_shared/repo_config_load.py",
    "skills/_shared/default_branch.py",
    "skills/_shared/bootstrap_immunization.py",
    "skills/_shared/ci_gate_run.py",
    "skills/_shared/ci_local_stamp.py",
    "skills/_shared/hooks/tp-commit-guard.sh",
    "skills/_shared/test_commit_guard.py",
    "skills/_shared/test_commit_guard_cli.py",
    "skills/_shared/test_commit_guard_hook.py",
    "skills/_shared/test_commit_guard_legacy.py",
    "skills/_shared/test_commit_guard_msg_hook.py",
    "skills/_shared/test_commit_guard_precommit_e2e.py",
    "skills/_shared/test_commit_guard_status.py",
    "skills/_shared/test_commit_guard_prose.py",
    "skills/_shared/test_repo_config_load.py",
    "skills/_shared/test_repo_config_load_committed.py",
    "skills/_shared/test_ci_gate_run.py",
    "skills/_shared/test_ci_local_stamp.py",
    "skills/_shared/test_ci_local_stamp_cli.py",
    "skills/_shared/test_ci_local_stamp_config_gate.py",
    "skills/_shared/test_ci_local_stamp_gate_command.py",
    "skills/_shared/test_ci_local_stamp_pred.py",
    "skills/_shared/test_default_branch.py",
    "skills/_shared/test_default_branch_callers.py",
    "skills/_shared/test_default_branch_ref.py",
    "skills/_shared/test_bootstrap_immunization.py",
    "skills/_shared/test_bootstrap_immunization_cli.py",
    "skills/_shared/test_bootstrap_immunization_r2.py",
    "skills/_shared/test_bootstrap_immunization_worktree.py",
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


def _src_argv(sha: str | None) -> list[str]:
    """The git argv prefix naming a diff source: a commit (``git show --format=
    <sha>``) or, for ``sha=None``, the index (``git diff --cached``, which also
    works on an unborn HEAD and honours an inherited ``GIT_INDEX_FILE``)."""
    if sha is None:
        return ["diff", "--cached", "--no-ext-diff"]
    return ["show", "--format=", sha]


def _label(sha: str | None) -> str:
    """The VIOLATION-line label: the short SHA, or ``staged`` for the index."""
    return "staged" if sha is None else sha[:12]


def _commit_files(src: list[str], repo: str) -> list[str]:
    """Return list of file paths changed in the ``src`` diff source (a
    ``_src_argv`` prefix) with --name-only, --no-renames.

    -z emits NUL-separated paths; git never C-quotes paths in -z mode so
    non-ASCII and special-character paths arrive verbatim, making prefix
    matching against EXCLUDED_PREFIXES unconditionally correct.
    """
    result = _git([*src, "--name-only", "--no-renames", "-z"], repo)
    # NUL-delimited output: split on NUL, drop genuinely empty tokens (leading
    # NUL from the empty --format= header, trailing NUL after the last path).
    # Do NOT strip() — a filename consisting entirely of spaces is a valid path
    # and must not be silently discarded.
    # Backslash normalization retained: Linux allows literal backslash in
    # filenames; normalise so callers need not handle both separators.
    paths = result.stdout.split("\0")
    return [p.replace("\\", "/") for p in paths if p]


def _numstat(src: list[str], repo: str) -> list[tuple[int | None, int | None, str]]:
    """Return (added, deleted, path) tuples from --numstat over the ``src``
    diff source (a ``_src_argv`` prefix).

    --no-renames ensures renames surface as delete+add of real paths so
    both the source and destination are separately checked.
    -z emits NUL-terminated records (adds\\tdels\\tpath\\0); git never C-quotes
    paths in -z mode, so special-character paths arrive verbatim.
    """
    result = _git([*src, "--numstat", "--no-renames", "-z"], repo)
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

def check_exclusions(sha: str | None, repo: str) -> list[str]:
    """Return VIOLATION messages if sha (None: the index) touches excluded
    paths; empty list if clean."""
    files = _commit_files(_src_argv(sha), repo)
    violations = []
    for f in files:
        f_norm = f.replace("\\", "/")
        if any(f_norm.startswith(p) for p in EXCLUDED_PREFIXES):
            violations.append(
                f"VIOLATION {_label(sha)} exclusion: touches protected prefix '{f_norm}'"
            )
        elif f_norm in EXCLUDED_FILES:
            violations.append(
                f"VIOLATION {_label(sha)} exclusion: touches protected file '{f_norm}'"
            )
    return violations


def check_diff_cap(sha: str | None, repo: str) -> list[str]:
    """Return VIOLATION messages if sha (None: the index) exceeds DIFF_CAP;
    empty list if clean.

    hot-patches.md is excluded from the sum (paper never eats the fix budget).
    Binary files (None counts) fail outright.
    """
    rows = _numstat(_src_argv(sha), repo)
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
                f"VIOLATION {_label(sha)} diff-cap: binary file '{path_norm}' — "
                "binary files are not permitted in hot-patch commits"
            ]
        total += added + deleted
    if total > DIFF_CAP:
        return [
            f"VIOLATION {_label(sha)} diff-cap: {total} changed lines exceeds cap of {DIFF_CAP}"
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
    p.add_argument(
        "--ledger-only", action="store_true",
        help="Run arm (a) only: ledger coverage (union ledger text) + the "
             "ledger-missing violation, skipping arms (b) and (c)",
    )
    p.add_argument(
        "--commit-msg", metavar="FILE",
        help="commit-msg hook mode: arm (b) on the pending commit. Inert unless "
             "FILE carries a hot-patch trailer; then exclusions + diff-cap over "
             "the index (hot_patch_hook.commit_msg_mode)",
    )
    p.add_argument(
        "--branch-trailered", action="store_true",
        help="pre-commit backstop: re-check every trailered commit in "
             "<default ref (origin first)>..HEAD (hot_patch_hook); combinable "
             "with --ledger-only",
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


def _run_arm_a(repo: str, ledger_path: Path, now_iso: str | None) -> list[str]:
    """Arm (a): ledger coverage over the union ledger text (both verifying
    default refs ∪ the `ledger_path` text), so an entry that landed on a ref
    we are not checked out of still discharges. Adds the no-grace
    ledger-missing violation when the ledger is absent everywhere and
    trailered commits exist.
    """
    local_text = (
        ledger_path.read_text(encoding="utf-8") if ledger_path.exists() else ""
    )
    ledger_text = union_ledger_text(repo, local_text)
    violations: list[str] = []
    if not ledger_text.strip() and _trailered_commits_on_head(repo):
        violations.append(
            "VIOLATION ledger-missing: hot-patches.md not found but trailered "
            "commits exist on the default branch"
        )
    violations.extend(
        check_ledger_coverage(repo=repo, ledger_text=ledger_text, now_iso=now_iso)
    )
    return violations


def _run_checks(args: argparse.Namespace, repo: str) -> int:
    """Execute all checks and return exit code."""
    violations: list[str] = []
    ledger_path = Path(args.ledger_file) if args.ledger_file else Path(repo) / LEDGER_RELPATH

    if args.commit_msg:
        # commit-msg hook mode (function-local import: hot_patch_hook imports
        # this module's helpers at module level, so no cycle).
        from skills._shared.hot_patch_hook import commit_msg_mode  # noqa: PLC0415
        return commit_msg_mode(repo, args.commit_msg)
    if args.branch_trailered:
        from skills._shared.hot_patch_hook import (  # noqa: PLC0415
            branch_trailered_violations,
        )
        violations.extend(branch_trailered_violations(repo))
    if args.ledger_only:
        # --ledger-only: arm (a) alone, over the union ledger text; no (b)/(c).
        violations.extend(_run_arm_a(repo, ledger_path, args.now))
    elif args.branch_trailered:
        pass  # --branch-trailered alone: the backstop only, never the full scan
    elif args.check_sha:
        # Pre-flight mode: check a single commit for exclusion + diff-cap only
        violations.extend(check_exclusions(sha=args.check_sha, repo=repo))
        violations.extend(check_diff_cap(sha=args.check_sha, repo=repo))
    else:
        # Full stanza mode: run arm (b) on all trailered commits (FULL history —
        # not just post-baseline; pre-baseline trailered commits are also checked).
        # Only arm (c) is baseline-scoped. Arms (a)/(b) sweep everything.

        # Arm (b): exclusion + diff-cap on every trailered commit on the default branch
        for sha in _trailered_commits_on_head(repo):
            violations.extend(check_exclusions(sha=sha, repo=repo))
            violations.extend(check_diff_cap(sha=sha, repo=repo))

        # Arm (a): ledger coverage deadline over the union ledger text.
        violations.extend(_run_arm_a(repo, ledger_path, args.now))

        # Arm (c): anomaly scan (post-baseline non-merge master commits)
        violations.extend(check_anomaly(repo=repo))

    for v in violations:
        print(v)

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
