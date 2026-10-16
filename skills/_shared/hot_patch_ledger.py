#!/usr/bin/env python3
"""hot_patch_ledger.py — ledger parsing, coverage deadline, and anomaly scan.

Split from hot_patch_check.py to keep both modules under the 500-line cap.
Imported by hot_patch_check.py for CLI use; do not call directly.

Stdlib only.
"""
from __future__ import annotations

import re
import subprocess
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

# Ensure _shared/ is on sys.path for sibling imports (diff_balloon_guard.py pattern).
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from default_branch import (  # noqa: E402
    DefaultBranchError,
    default_branch_names,
    default_ref,
    resolve_default_branch,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASELINE = "2026-06-12T23:59:59Z"  # anomaly baseline date pin (committer date)
# Inclusive at exactly this timestamp: --since-as-filter matches >= BASELINE.
LEDGER_RELPATH = "three-pillars-docs/tp-designs/orchestration/hot-patches.md"

# Framework paths flagged by the anomaly scan (post-baseline non-merge commits)
FRAMEWORK_PREFIXES = (
    "skills/",
    "framework-check.sh",
    "test-framework-check.sh",
    ".three-pillars/",
    "scripts/fc-selftest/",
)

# Anomaly carve-out: three-pillars-docs/ paths are implicitly exempt (no overlap with FRAMEWORK_PREFIXES).

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
    return subprocess.run(["git", "-C", repo] + args,
                          capture_output=True, text=True, check=check)


def _resolve_scan_ref(repo: str) -> str | None:
    """default_ref, with a plain-verify fallback for a ref default_branch's
    stricter object-existence check rejects (e.g. a corrupted object store) —
    a git-log-time failure that must still reach git log/show (fail-closed),
    not the degraded-clone warning."""
    ref = default_ref(repo, prefer="local")
    if ref is not None:
        return ref
    for name in default_branch_names(repo):
        r = subprocess.run(["git", "-C", repo, "rev-parse", "--verify", name],
                           capture_output=True, text=True)
        if r.returncode == 0:
            return name
    return None


def union_ledger_text(repo: str, local_text: str) -> str:
    """Union of the ledger text at both verifying default refs and `local_text`.

    `local_text` is the work-tree ledger text or the `--ledger-file` text (empty
    string if neither exists). For the resolved default-branch name `<n>`, the
    ledger is read from `<n>:LEDGER_RELPATH` and `origin/<n>:LEDGER_RELPATH`
    via `git show`; a ref that does not verify or that lacks the file
    contributes nothing, and a `DefaultBranchError` (no refs) is caught.
    Concatenation is the union: a ledger entry only discharges, and
    `parse_ledger` parses each line independently, so duplicates are harmless.
    """
    chunks: list[str] = []
    try:
        name = resolve_default_branch(repo)
    except DefaultBranchError:
        name = None
    if name is not None:
        for ref in (name, f"origin/{name}"):
            result = subprocess.run(
                ["git", "-C", repo, "show", f"{ref}:{LEDGER_RELPATH}"],
                capture_output=True, text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                chunks.append(result.stdout)
    if local_text:
        chunks.append(local_text)
    return "\n".join(chunks)


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
    """Full SHAs of commits on the resolved default-branch ref carrying a
    hot-patch trailer (any key casing: 'hot-patch', 'Hot-Patch', 'HOT-PATCH :').

    Prefilter with `git log -i --grep=^hot-patch` (admits mid-message mentions
    too), then confirm each candidate by the `%(trailers:key=hot-patch)` parse
    (a mid-message `hot-patch:` line is NOT a trailer and is dropped). Only
    confirmed SHAs count; no hits → [] without the confirm call. Scans only
    the resolved ref, never --all. Raises RuntimeError on git log failure."""
    head_ref = _resolve_scan_ref(repo)
    if head_ref is None:
        warnings.warn(
            "hot_patch_check: no default-branch ref resolves; "
            "trailered-commit scan skipped (degraded clone)",
            stacklevel=2,
        )
        return []

    result = subprocess.run(
        ["git", "-C", repo, "log", head_ref, "-i", "--grep=^hot-patch", "--format=%H"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git log failed (exit {result.returncode}): {result.stderr.strip()}")
    candidates = [s for s in (ln.strip() for ln in result.stdout.splitlines()) if _SHA40_RE.match(s)]
    if not candidates:
        return []

    fmt = "%H %(trailers:key=hot-patch,valueonly,separator=%x2C,unfold=true)"
    confirm = subprocess.run(["git", "-C", repo, "log", "--no-walk", *candidates, f"--format={fmt}"],
                             capture_output=True, text=True)
    if confirm.returncode != 0:
        raise RuntimeError(f"git log failed (exit {confirm.returncode}): {confirm.stderr.strip()}")
    confirmed = []
    for line in confirm.stdout.splitlines():
        parts = line.strip().split(" ", 1)
        if len(parts) == 2 and _SHA40_RE.match(parts[0]) and parts[1].strip():
            confirmed.append(parts[0])
    return confirmed


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

    entries = [
        {"sha": m.group(1), "date": m.group(2), "trigger": m.group(3).strip(),
         "broke": m.group(4).strip(), "fix": m.group(5).strip(),
         "touched": m.group(6).strip()}
        for m in LEDGER_ENTRY_RE.finditer(body)
    ]

    # Near-miss diagnostic: lines that look like entries but did not parse.
    # Check the stripped line (must match LEDGER_ENTRY_RE) and the raw line
    # (must be anchored at column 0 — indented entries are not parsed).
    for raw_line in body.splitlines():
        stripped = raw_line.strip()
        if not stripped.startswith("- "):
            continue
        if LEDGER_ENTRY_RE.match(stripped) and not raw_line.startswith("-"):
            # Looks valid but was not at column 0 → indented
            print(f"hot_patch_check: indented ledger entry not parsed: {raw_line!r}",
                  file=sys.stderr)
        elif not LEDGER_ENTRY_RE.match(stripped):
            # Starts with "- " but doesn't match the full regex
            print(f"hot_patch_check: ledger line looks like an entry but failed to parse: "
                  f"{stripped!r}", file=sys.stderr)
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
    """VIOLATION messages for post-baseline unsanctioned non-merge commits.

    Scans --first-parent --no-merges --since-as-filter=BASELINE (git >= 2.37,
    full-history traversal so a backdated commit can't hide later ones) on the
    resolved default branch. Docs-only commits are silent (three-pillars-docs/**
    can never match FRAMEWORK_PREFIXES); no ref resolves → warn + skip. Arm (c)
    keys on committer date (a determined actor can backdate; accepted limit).
    Raises RuntimeError on git log failure so caller exits 2."""
    head_ref = _resolve_scan_ref(repo)

    if head_ref is None:
        warnings.warn(
            "hot_patch_check: no default-branch ref resolves; "
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
