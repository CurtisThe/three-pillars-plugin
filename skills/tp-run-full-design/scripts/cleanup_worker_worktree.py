"""Remove a worker worktree, recording when a lock had to be forced.

Used by the tp-run-full-design orchestrator (tier 3.5) to tear down worker
worktrees once a candidate has been merged or discarded.

Signature is canonical — `decisions_log` defaults to None so unit tests stay
free of global side effects; the orchestrator passes the design's
`decisions.md` path so the audit trail is preserved at runtime.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_LOG_PREFIX = "[tp-run-full-design/tier-3.5] worktree-cleanup-locked"


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
