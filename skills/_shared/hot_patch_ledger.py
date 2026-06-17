#!/usr/bin/env python3
"""hot_patch_ledger.py — ledger parsing, coverage deadline, and anomaly scan.

Split from hot_patch_check.py to keep both modules under the 500-line cap.
Imported by hot_patch_check.py for CLI use; do not call directly.

Stdlib only.
"""
from __future__ import annotations

import re
import subprocess
import warnings
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASELINE = "2026-06-12T23:59:59Z"  # anomaly baseline date pin (committer date)
# Inclusive at exactly this timestamp: --since-as-filter matches >= BASELINE
# (accepted one-second edge; all six evidence commits predate it by days).
LEDGER_RELPATH = "three-pillars-docs/tp-designs/orchestration/hot-patches.md"

# Framework paths flagged by the anomaly scan (post-baseline non-merge commits)
FRAMEWORK_PREFIXES = (
    "skills/",
    "framework-check.sh",
    "test-framework-check.sh",
    ".three-pillars/",
)

# Anomaly carve-out: three-pillars-docs/ paths are implicitly exempt because
# no docs path can ever match FRAMEWORK_PREFIXES (no overlap by construction).

LEDGER_ENTRY_RE = re.compile(
    r"^-\s+([0-9a-f]{7,})\s+\|\s+(\d{4}-\d{2}-\d{2})\s+\|\s+trigger:\s*([^|]+?)\s*\|"
    r"\s+broke:\s*([^|]+?)\s*\|\s+fix:\s*([^|]+?)\s*\|\s+touched:\s*(.+?)\s*$",
    re.MULTILINE,
)

# Regex for validating SHA tokens from git log --format trailer output
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")


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


def _commit_date_utc(sha: str, repo: str) -> str | None:
    """Return committer date for sha as YYYY-MM-DD in UTC.

    Returns None on git failure; caller emits VIOLATION date-unreadable.
    """
    result = _git(["show", "-s", "--format=%cI", sha], repo, check=False)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    raw = result.stdout.strip()
    try:
        dt = datetime.fromisoformat(raw).astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, OverflowError):
        return None


def _trailered_commits_on_head(repo: str) -> list[str]:
    """Return full SHAs of commits on HEAD that carry a hot-patch trailer.

    Scans only the default branch HEAD (master then origin/master) — never --all.
    Unmerged hot-patch PRs never incur a ledger obligation.

    Raises RuntimeError on git log failure so caller exits 2.
    """
    # Resolve the default branch ref
    for ref in ("master", "origin/master"):
        r = subprocess.run(
            ["git", "-C", repo, "rev-parse", "--verify", ref],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            head_ref = ref
            break
    else:
        warnings.warn(
            "hot_patch_check: neither 'master' nor 'origin/master' resolves; "
            "trailered-commit scan skipped (degraded clone)",
            stacklevel=2,
        )
        return []

    # unfold=true avoids multi-line folded trailer issues.
    # Validate each SHA token against ^[0-9a-f]{40}$ to skip parser garbage.
    result = subprocess.run(
        ["git", "-C", repo, "log", head_ref,
         "--format=%H %(trailers:key=hot-patch,valueonly,separator=%x2C,unfold=true)"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git log failed (exit {result.returncode}): {result.stderr.strip()}"
        )

    shas = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(" ", 1)
        sha = parts[0]
        # Validate full SHA token to catch parser garbage
        if not _SHA40_RE.match(sha):
            continue
        trailer_val = parts[1].strip() if len(parts) > 1 else ""
        if trailer_val:
            shas.append(sha)
    return shas


# ---------------------------------------------------------------------------
# Exported predicates
# ---------------------------------------------------------------------------

def parse_ledger(text: str) -> list[dict]:
    """Parse ledger text and return list of entry dicts.

    Each dict has keys: sha, date, trigger, broke, fix, touched.
    Only lines after the '<!-- entries below -->' anchor are parsed.
    """
    anchor = "<!-- entries below -->"
    idx = text.find(anchor)
    if idx == -1:
        body = text
    else:
        body = text[idx + len(anchor):]

    entries = []
    for m in LEDGER_ENTRY_RE.finditer(body):
        entries.append({
            "sha": m.group(1),
            "date": m.group(2),
            "trigger": m.group(3).strip(),
            "broke": m.group(4).strip(),
            "fix": m.group(5).strip(),
            "touched": m.group(6).strip(),
        })

    # Near-miss diagnostic: lines that look like entries but did not parse.
    # Check both the stripped line (must match LEDGER_ENTRY_RE) and the raw
    # line (must be anchored at column 0 — indented entries are not parsed).
    import sys as _sys  # noqa: PLC0415
    for raw_line in body.splitlines():
        stripped = raw_line.strip()
        if not stripped.startswith("- "):
            continue
        if LEDGER_ENTRY_RE.match(stripped):
            # Looks syntactically valid but was not at column 0 → indented
            if not raw_line.startswith("-"):
                print(
                    f"hot_patch_check: indented ledger entry not parsed: {raw_line!r}",
                    file=_sys.stderr,
                )
        else:
            # Starts with "- " but doesn't match the full regex
            print(
                f"hot_patch_check: ledger line looks like an entry but failed to parse: "
                f"{stripped!r}",
                file=_sys.stderr,
            )
    return entries


def _sha_covered(commit_sha: str, entries: list[dict]) -> bool:
    """Return True if any ledger entry SHA is a prefix of commit_sha (>=7 chars)."""
    for entry in entries:
        entry_sha = entry["sha"]
        if len(entry_sha) >= 7 and commit_sha.startswith(entry_sha):
            return True
    return False


def check_ledger_coverage(
    repo: str,
    ledger_text: str,
    now_iso: str | None = None,
) -> list[str]:
    """Return VIOLATION messages for overdue ledger entries; empty list if clean.

    Scans only trailered commits on the default branch HEAD (never --all).
    A commit is "overdue" when it has no ledger entry AND now is past its
    UTC calendar day (same-day fail-closed: Behavior 3).
    """
    from datetime import timedelta  # noqa: PLC0415

    if now_iso is not None:
        now_dt = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    else:
        now_dt = datetime.now(timezone.utc)

    entries = parse_ledger(ledger_text)
    trailered = _trailered_commits_on_head(repo)
    violations = []

    for sha in trailered:
        if _sha_covered(sha, entries):
            continue
        # Check if still within same-day window
        commit_date_str = _commit_date_utc(sha, repo)
        if commit_date_str is None:
            violations.append(
                f"VIOLATION {sha[:12]} date-unreadable: could not read committer date"
            )
            continue
        try:
            commit_date = datetime.strptime(commit_date_str, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            violations.append(
                f"VIOLATION {sha[:12]} date-unreadable: could not parse date {commit_date_str!r}"
            )
            continue
        # The window expires at end of the commit's UTC calendar day
        # (i.e., the start of the next day)
        window_end = commit_date + timedelta(days=1)
        if now_dt >= window_end:
            violations.append(
                f"VIOLATION {sha[:12]} ledger-overdue: trailered commit missing "
                f"hot-patches.md entry; deadline was {commit_date_str} UTC end-of-day"
            )
    return violations


def check_anomaly(repo: str) -> list[str]:
    """Return VIOLATION messages for post-baseline unsanctioned non-merge commits.

    Scans --first-parent --no-merges --since-as-filter=BASELINE on master.
    Using --since-as-filter (git >= 2.37) ensures full-history traversal so a
    backdated commit cannot truncate the walk and hide later post-baseline commits.
    Commits touching only three-pillars-docs/** are silent (carve-out implied:
    docs paths can never match FRAMEWORK_PREFIXES).
    When neither master nor origin/master resolves, warns and skips (degraded clone).

    Arm (c) keys on committer date, which a determined actor can backdate.
    Accepted limitation: this lane's threat model is honest-operator-under-pressure,
    not adversarial forgery.

    Raises RuntimeError on git log failure so caller exits 2.
    """
    # Resolve the default branch ref
    head_ref = None
    for ref in ("master", "origin/master"):
        r = subprocess.run(
            ["git", "-C", repo, "rev-parse", "--verify", ref],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            head_ref = ref
            break

    if head_ref is None:
        warnings.warn(
            "hot_patch_check: neither 'master' nor 'origin/master' resolves; "
            "anomaly scan skipped (degraded clone)",
            stacklevel=2,
        )
        return []

    result = subprocess.run(
        ["git", "-C", repo, "log", head_ref,
         "--first-parent", "--no-merges",
         f"--since-as-filter={BASELINE}",
         "--format=%H"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git log (anomaly scan) failed (exit {result.returncode}): "
            f"{result.stderr.strip()}"
        )

    violations = []
    for sha in result.stdout.splitlines():
        sha = sha.strip()
        if not sha:
            continue
        files = _commit_files_for_anomaly(sha, repo)
        if not files:
            continue
        # Check if any file touches framework paths
        touches_framework = any(
            any(f.replace("\\", "/").startswith(p) for p in FRAMEWORK_PREFIXES)
            for f in files
        )
        if touches_framework:
            violations.append(
                f"VIOLATION {sha[:12]} anomaly: post-baseline non-merge commit "
                "touches framework paths — use the hot-patch lane (invariant #37)"
            )
    return violations


def _commit_files_for_anomaly(sha: str, repo: str) -> list[str]:
    """Return list of file paths changed in sha (--name-only, --no-renames).

    Uses check=True for fail-closed posture: a git show failure (e.g. corrupt
    object) raises CalledProcessError rather than silently returning no files
    (which would hide an anomalous commit from the scan).
    -z emits NUL-separated paths; git never C-quotes paths in -z mode so
    non-ASCII and special-character paths arrive verbatim, making prefix
    matching against FRAMEWORK_PREFIXES unconditionally correct.
    """
    result = subprocess.run(
        ["git", "-C", repo,
         "show", "--name-only", "--no-renames", "-z", "--format=", sha],
        capture_output=True, text=True, check=True,
    )
    # NUL-delimited output: split on NUL, drop genuinely empty tokens (leading
    # NUL from the empty --format= header, trailing NUL after the last path).
    # Do NOT strip() — a filename consisting entirely of spaces is a valid path
    # and must not be silently discarded.
    # Backslash normalization retained: Linux allows literal backslash in
    # filenames; normalise so prefix matching works for both separators.
    paths = result.stdout.split("\0")
    return [p.replace("\\", "/") for p in paths if p]
