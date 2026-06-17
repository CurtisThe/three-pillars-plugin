"""pr_state.py — reusable per-branch PR-state predicate.

Queries `gh pr view <branch> --json state,mergedAt,number,headRefName` and
returns a structured PrVerdict with state in the closed set:

  MERGED   — PR exists and was merged
  OPEN     — PR exists and is open
  CLOSED   — PR exists but was closed without merging
  NO_PR    — gh positively confirms no PR for this branch
  UNKNOWN  — gh failed / not installed / network error / malformed JSON

IMPORTANT — remote-branch absence is NOT teardown/merge evidence.
GitHub auto-delete-on-merge means a remote branch can vanish while the
branch state is MERGED (not deleted/un-worked). The PR-state predicate
is the only trustworthy signal; this module never checks branch existence.

Reusable shape: zero imports from worktree scripts; zero gc-only
assumptions. Consumers: gc_residue.py, fleet-recovery-barbell (future).

CLI: python3 pr_state.py <branch> [--cwd <path>] → one JSON line on stdout.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

VALID_STATES = {"MERGED", "OPEN", "CLOSED", "NO_PR", "UNKNOWN"}

# Substrings in gh stderr that indicate "no PR found" (a positive answer).
# These are the ONLY two markers that represent a genuine no-PR reply from gh.
# Bare "404" is intentionally excluded: any gh failure that emits "404" (repo
# not found, expired auth, SAML-blocked, wrong remote) would otherwise be
# classified as the positive NO_PR verdict, which is deletion evidence for
# agent branches.  Such failures must map to UNKNOWN, not NO_PR.
_NO_PR_MARKERS = ("no pull requests", "could not resolve to a pullrequest")


# ---------------------------------------------------------------------------
# Verdict dataclass
# ---------------------------------------------------------------------------


@dataclass
class PrVerdict:
    """Structured result from the PR-state predicate.

    state     — one of VALID_STATES (closed set)
    merged_at — ISO-8601 UTC string if MERGED, else None
    evidence  — raw gh fields dict (may be empty on UNKNOWN/NO_PR)
    """

    state: str
    merged_at: Optional[str]
    evidence: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal gh subprocess helper (monkeypatched in tests)
# ---------------------------------------------------------------------------


def _run_gh(branch: str, cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    """Run gh pr view <branch> --json ... and return CompletedProcess."""
    return subprocess.run(
        [
            "gh", "pr", "view", branch,
            "--json", "state,mergedAt,number,headRefName",
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# Core predicate
# ---------------------------------------------------------------------------


def pr_state(branch: str, cwd: Optional[Path] = None) -> PrVerdict:
    """Return a PrVerdict for `branch`.

    Never raises — any gh failure produces UNKNOWN.
    Remote-branch absence is NOT checked and is NOT evidence of any state.
    """
    try:
        result = _run_gh(branch, cwd)
    except Exception:
        return PrVerdict(state="UNKNOWN", merged_at=None, evidence={})

    # Non-zero exit — check if it's a "no PR" reply or an error.
    if result.returncode != 0:
        stderr_lower = (result.stderr or "").lower()
        if any(marker in stderr_lower for marker in _NO_PR_MARKERS):
            return PrVerdict(state="NO_PR", merged_at=None, evidence={})
        return PrVerdict(state="UNKNOWN", merged_at=None, evidence={})

    # Parse JSON response.
    try:
        data = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return PrVerdict(state="UNKNOWN", merged_at=None, evidence={})

    raw_state = (data.get("state") or "").upper()
    merged_at = data.get("mergedAt") or None

    if raw_state == "MERGED":
        return PrVerdict(state="MERGED", merged_at=merged_at, evidence=data)
    if raw_state == "OPEN":
        return PrVerdict(state="OPEN", merged_at=None, evidence=data)
    if raw_state == "CLOSED":
        return PrVerdict(state="CLOSED", merged_at=None, evidence=data)

    # Unexpected state string → UNKNOWN
    return PrVerdict(state="UNKNOWN", merged_at=None, evidence=data)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    """Print a JSON line for a branch's PR state.

    Usage: python3 pr_state.py <branch> [--cwd <path>]
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Query GitHub PR state for a branch (one JSON line output)."
    )
    parser.add_argument("branch", help="Branch name to query.")
    parser.add_argument("--cwd", default=None, help="Working directory for gh (default: cwd).")
    args = parser.parse_args()

    cwd = Path(args.cwd).resolve() if args.cwd else None
    verdict = pr_state(args.branch, cwd=cwd)
    print(json.dumps({
        "branch": args.branch,
        "state": verdict.state,
        "merged_at": verdict.merged_at,
        "evidence": verdict.evidence,
    }))


if __name__ == "__main__":
    main()
