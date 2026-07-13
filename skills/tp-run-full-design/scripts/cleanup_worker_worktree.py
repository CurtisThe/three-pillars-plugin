"""Remove a worker worktree, recording when a lock had to be forced.

Used by the tp-run-full-design orchestrator (tier 3.5) to tear down worker
worktrees once a candidate has been merged or discarded.

Signature is canonical — `decisions_log` defaults to None so unit tests stay
free of global side effects; the orchestrator passes the design's
`decisions.md` path so the audit trail is preserved at runtime.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_LOG_PREFIX = "[tp-run-full-design/tier-3.5] worktree-cleanup-locked"
_ORPHAN_BRANCH_PREFIX = "worktree-agent-"
_SWEEP_LOG_PREFIX = "[tp-run-full-design/tier-3.5] worktree-agent-branch-deleted"


def _is_locked(worktree_path: Path) -> bool:
    """True if ``worktree_path`` is a locked worktree per ``git worktree list``.

    ``git worktree list --porcelain`` emits a ``locked`` attribute line for each
    worktree the repo has marked locked (e.g. a claude agent holding it). We
    return True when the entry whose ``worktree <path>`` record matches our
    target carries that attribute.

    Advisory and **fail-open**: this only decides whether the removal counts as a
    forced-lock event worth recording in the OQ5 audit trail. Double-force
    ``remove`` removes a locked worktree outright regardless, so if the lock
    query itself fails for any reason — or a path mismatch (e.g. symlinked
    parents) hides the match — we return False and let the removal proceed
    without an audit line. The query must never abort cleanup.
    """
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        )
        target = str(worktree_path.resolve())
        current = None
        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                current = str(Path(line[len("worktree "):]).resolve())
            elif line.startswith("locked") and current == target:
                return True
        return False
    except (subprocess.SubprocessError, OSError):
        return False


def _checked_out_branches() -> set[str]:
    """Short branch names currently checked out by any live worktree.

    Parses ``git worktree list --porcelain`` the same shape as ``_is_locked``
    but extracts the ``branch refs/heads/<name>`` short name instead of the
    path — normalized (R4) by stripping ``refs/heads/`` so it lines up with
    the short names ``git branch --list --format=%(refname:short)`` returns.
    Comparing full-vs-short ref forms would make this exclusion set dead
    code, saved only by git's own ``-D``-on-checked-out-branch refusal.

    Fail-open to an empty set on any error: an empty set means every
    ``worktree-agent-*`` candidate is attempted, which stays safe because
    the caller's name guard and git's own refusal are the remaining layers.
    """
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.SubprocessError, OSError):
        return set()
    checked_out: set[str] = set()
    for line in result.stdout.splitlines():
        if line.startswith("branch "):
            ref = line[len("branch "):].strip()
            if ref.startswith("refs/heads/"):
                ref = ref[len("refs/heads/"):]
            checked_out.add(ref)
    return checked_out


def sweep_orphan_agent_branches(decisions_log: Path | None = None) -> list[str]:
    """Delete every local ``worktree-agent-*`` branch not checked out by a
    live worktree (design.md Option A / plan Mechanism-refinement note).

    Name-guarded: ``worktree-agent-`` is a hard precondition, re-checked per
    candidate even though the ``--list`` glob already filters — a mocked or
    unusual git build must never let a non-matching name through. Fail-open
    at every step: a git failure anywhere yields fewer (never zero-crash)
    deletions, and this function never raises.

    Returns the list of branch names actually deleted (for logging/tests).
    """
    checked_out = _checked_out_branches()

    try:
        result = subprocess.run(
            [
                "git", "branch", "--list", f"{_ORPHAN_BRANCH_PREFIX}*",
                "--format=%(refname:short)",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        candidates = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    except (subprocess.SubprocessError, OSError):
        candidates = []

    deleted: list[str] = []
    for name in candidates:
        if not name.startswith(_ORPHAN_BRANCH_PREFIX):
            continue
        if name in checked_out:
            continue
        try:
            result = subprocess.run(
                ["git", "branch", "-D", name],
                check=False,
                capture_output=True,
            )
        except (subprocess.SubprocessError, OSError):
            continue
        if result.returncode == 0:
            deleted.append(name)

    if deleted and decisions_log is not None:
        try:
            with open(decisions_log, "a", encoding="utf-8") as fh:
                for name in deleted:
                    fh.write(f"{_SWEEP_LOG_PREFIX} {name}\n")
        except OSError:
            pass

    return deleted


def cleanup_worker_worktree(
    worktree_path: Path,
    decisions_log: Path | None = None,
) -> None:
    """Remove the worktree at ``worktree_path``; force through claude-agent locks.

    - If the path is already absent on disk, returns silently.
    - Removes with double-force (``--force -f``) — S13 F9 / the P1 dogfood probe
      found single ``--force`` fails on a locked / at-depth worktree while
      ``--force -f`` removes a locked or nested worktree outright, so no separate
      unlock + retry step is needed.
    - When the worktree was locked AND ``decisions_log`` is not None, appends a
      single audit line to that log (OQ5 cleanup audit convention).
    - Path-generic: works for any tier worktree the orchestrator creates.
    """
    if not worktree_path.exists():
        return

    was_locked = _is_locked(worktree_path)

    subprocess.run(
        ["git", "worktree", "remove", "--force", "-f", str(worktree_path)],
        check=True,
        capture_output=True,
    )

    if was_locked and decisions_log is not None:
        with open(decisions_log, "a", encoding="utf-8") as fh:
            fh.write(f"{_LOG_PREFIX} {worktree_path}\n")

    # Option A trigger (design.md Behaviors / plan Mechanism-refinement note):
    # the just-removed worktree has dropped out of `git worktree list`, so its
    # now-orphaned `worktree-agent-<id>` auto-branch is no longer excluded and
    # gets swept here — the Open-Q1 safe-delete point (after removal, never
    # before). R1 (adversarial HIGH): the caller (run_tier_3_5.py) escalates
    # on ANY exception raised by this function, so the sweep gets its OWN
    # bare try/except here — a failure inside the sweep (or its decisions.md
    # append) must never turn a clean teardown into a false "cleanup-failed"
    # escalation, regardless of what the helper's own internal catch list
    # covers.
    try:
        sweep_orphan_agent_branches(decisions_log=decisions_log)
    except Exception as exc:  # noqa: BLE001 - deliberate fail-open backstop
        print(
            f"[tp-run-full-design/tier-3.5] orphan-branch sweep failed: {exc}",
            file=sys.stderr,
        )
