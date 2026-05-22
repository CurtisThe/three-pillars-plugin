"""Remove a worker worktree, recovering from claude-agent locks.

Used by the tp-run-full-design orchestrator (tier 3.5) to tear down
worker worktrees once a candidate has been merged or discarded.

Signature is canonical — `decisions_log` defaults to None so unit tests
stay free of global side effects; the orchestrator passes the design's
`decisions.md` path so the audit trail is preserved at runtime.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_LOCK_MARKER = b"locked by claude agent"
_LOG_PREFIX = "[tp-run-full-design/tier-3.5] worktree-cleanup-retry"


def _stderr_has_lock_marker(stderr: bytes | str | None) -> bool:
    if stderr is None:
        return False
    if isinstance(stderr, str):
        return _LOCK_MARKER.decode() in stderr
    return _LOCK_MARKER in stderr


def cleanup_worker_worktree(
    worktree_path: Path,
    decisions_log: Path | None = None,
) -> None:
    """Remove a worktree at ``worktree_path``; recover from claude-agent locks.

    - If the path is already absent on disk, returns silently.
    - On the first attempt's lock-held failure, unlocks then retries with
      ``--force`` (no ``-f`` shorthand on the retry to mirror git's expected
      post-unlock invocation).
    - When the retry path is taken AND ``decisions_log`` is not None, appends
      a single audit line to that log.
    """
    if not worktree_path.exists():
        return

    path_str = str(worktree_path)

    try:
        subprocess.run(
            ["git", "worktree", "remove", "--force", "-f", path_str],
            check=True,
            capture_output=True,
        )
        return
    except subprocess.CalledProcessError as exc:
        if not _stderr_has_lock_marker(exc.stderr):
            raise

    # Lock-held: unlock and retry.
    subprocess.run(
        ["git", "worktree", "unlock", path_str],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "worktree", "remove", "--force", path_str],
        check=True,
        capture_output=True,
    )

    if decisions_log is not None:
        with open(decisions_log, "a", encoding="utf-8") as fh:
            fh.write(f"{_LOG_PREFIX} {worktree_path}\n")
