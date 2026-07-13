"""gc_candidate_branches_apply.py — apply engine for the candidate/* reaper.

Consumes classification rows from gc_candidate_branches.classify_candidates()
(duck-typed on `.action` / `.surface` / `.branch` / `.evidence`) and performs the
deletions for `action == "deletable"` rows only:

  - local rows  → `git branch -D <branch>`            (fail-open PER REF)
  - remote rows → batched `git push origin --delete <ref>...` (fail-open PER BATCH)

Safety discipline (mirrors teardown steps 5e/5g + gc_residue_apply):
  - Dry-run is the DEFAULT (apply=False): ZERO mutations; emit `dry-run` verdicts
    carrying the exact command each surface WOULD run.
  - `--apply` really deletes; a failed local ref or a failed remote BATCH never
    aborts the remainder (fail-open), and every outcome is reported.
  - Remote deletes are BATCHED (≤ batch_size per `git push`) to bound blast radius.
  - fetch_ok=False → suppress the AGE-axis remote deletes (report-only) so a stale
    tracking cache can never drive a stale remote delete (design B6 / audit F3).
    Merge-axis remote deletes (parent MERGED — a positive fact, not stale state)
    are UNAFFECTED, and local deletes (local refs are ground truth) always proceed.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class DeleteVerdict:
    """Per-ref result from apply_deletions().

    action_taken:
      dry-run                — no mutation attempted (apply=False)
      deleted                — the delete succeeded
      delete-failed          — the delete was attempted and failed (fail-open)
      suppressed-stale-fetch — age-axis remote delete withheld (fetch failed)
    """

    branch: str
    surface: str          # "local" | "remote"
    action_taken: str
    command: str          # the exact git command (batched for remote surfaces)
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Internal git helpers (monkeypatched in tests)
# ---------------------------------------------------------------------------


def _delete_local_branch(repo: Path, branch: str) -> tuple[bool, str]:
    """`git branch -D <branch>`. Returns (ok, stderr). Never raises."""
    result = subprocess.run(
        ["git", "branch", "-D", branch],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    return (result.returncode == 0, result.stderr.strip())


def _push_delete_batch(repo: Path, branches: list[str]) -> tuple[bool, str]:
    """`git push origin --delete <branch>...` for a whole batch.

    Returns (ok, stderr). Never raises. The batch is the fail-open unit: a
    non-zero exit fails the batch as a whole without aborting later batches.
    """
    result = subprocess.run(
        ["git", "push", "origin", "--delete", *branches],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    return (result.returncode == 0, result.stderr.strip())


# ---------------------------------------------------------------------------
# Core apply
# ---------------------------------------------------------------------------


def _axis(row) -> Optional[str]:
    """The firing axis ('age' | 'merge') from a deletable row's evidence."""
    return (getattr(row, "evidence", None) or {}).get("axis")


def apply_deletions(
    rows: list,
    *,
    repo: Path,
    apply: bool = False,
    batch_size: int = 10,
    fetch_ok: bool = True,
) -> list[DeleteVerdict]:
    """Delete the deletable rows (local first, then batched remotes).

    Only `action == "deletable"` rows are touched; everything else is ignored.
    Dry-run (apply=False, default) mutates nothing and returns `dry-run` verdicts
    with the exact commands. `--apply` performs the deletions fail-open.

    When `fetch_ok` is False, AGE-axis remote deletes are suppressed (report-only);
    merge-axis remote deletes and all local deletes are unaffected.
    """
    repo = Path(repo)
    # Defensive floor: a bogus batch_size (0 → ValueError in range(); <0 → skips
    # every remote delete) can never be trusted from the caller, so clamp to 1.
    batch_size = max(1, batch_size)
    deletable = [r for r in rows if getattr(r, "action", None) == "deletable"]
    local_rows = [r for r in deletable if r.surface == "local"]
    remote_rows = [r for r in deletable if r.surface == "remote"]

    verdicts: list[DeleteVerdict] = []

    # --- Local deletes (fail-open per ref) ---
    for row in local_rows:
        cmd = f"git branch -D {row.branch}"
        if not apply:
            verdicts.append(DeleteVerdict(row.branch, "local", "dry-run", cmd))
            continue
        ok, err = _delete_local_branch(repo, row.branch)
        verdicts.append(DeleteVerdict(
            row.branch, "local",
            "deleted" if ok else "delete-failed", cmd,
            error=None if ok else err,
        ))

    # --- Remote deletes: suppress age-axis when the fetch was stale/failed ---
    to_delete: list = []
    for row in remote_rows:
        if not fetch_ok and _axis(row) == "age":
            verdicts.append(DeleteVerdict(
                row.branch, "remote", "suppressed-stale-fetch",
                f"git push origin --delete {row.branch}",
            ))
            continue
        to_delete.append(row)

    # --- Batched remote deletes (fail-open per batch) ---
    for i in range(0, len(to_delete), batch_size):
        batch = to_delete[i:i + batch_size]
        branches = [r.branch for r in batch]
        cmd = "git push origin --delete " + " ".join(branches)
        if not apply:
            for r in batch:
                verdicts.append(DeleteVerdict(r.branch, "remote", "dry-run", cmd))
            continue
        ok, err = _push_delete_batch(repo, branches)
        for r in batch:
            verdicts.append(DeleteVerdict(
                r.branch, "remote",
                "deleted" if ok else "delete-failed", cmd,
                error=None if ok else err,
            ))

    return verdicts
