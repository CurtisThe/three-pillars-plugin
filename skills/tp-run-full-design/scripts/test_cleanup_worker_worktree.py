"""Tests for cleanup_worker_worktree helper.

Covers the five behaviors specified in Task 1.4 of tp-run-full-design plan:
  (a) happy path: single `git worktree remove --force -f <path>` call.
  (b) lock-held retry: unlock then retry remove --force <path>.
  (c) already-removed: no subprocess call when path missing.
  (d) retry-path audit log written when decisions_log provided.
  (e) retry-path audit log silent when decisions_log is None (default).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cleanup_worker_worktree import cleanup_worker_worktree


def _ok() -> MagicMock:
    """Return a CompletedProcess-like stand-in for a successful subprocess.run."""
    result = MagicMock()
    result.returncode = 0
    result.stderr = b""
    result.stdout = b""
    return result


def _lock_held_error(path: str) -> subprocess.CalledProcessError:
    err = subprocess.CalledProcessError(
        returncode=128,
        cmd=["git", "worktree", "remove", "--force", "-f", path],
    )
    err.stderr = (
        f"fatal: '{path}' is locked by claude agent; use --force or unlock"
    ).encode()
    err.stdout = b""
    return err


# ---------------------------------------------------------------------------
# (a) happy path
# ---------------------------------------------------------------------------
def test_happy_path_single_remove_call(tmp_path):
    wt = tmp_path / "worker-1"
    wt.mkdir()

    with patch("cleanup_worker_worktree.subprocess.run") as run:
        run.return_value = _ok()
        cleanup_worker_worktree(wt)

    assert run.call_count == 1
    args, kwargs = run.call_args
    assert args[0] == ["git", "worktree", "remove", "--force", "-f", str(wt)]
    assert kwargs.get("check") is True


# ---------------------------------------------------------------------------
# (b) lock-held retry path
# ---------------------------------------------------------------------------
def test_lock_held_unlocks_and_retries(tmp_path):
    wt = tmp_path / "worker-2"
    wt.mkdir()

    with patch("cleanup_worker_worktree.subprocess.run") as run:
        run.side_effect = [
            _lock_held_error(str(wt)),  # first remove --force -f fails
            _ok(),                        # unlock succeeds
            _ok(),                        # second remove --force succeeds
        ]
        cleanup_worker_worktree(wt)

    assert run.call_count == 3
    first_call = run.call_args_list[0]
    unlock_call = run.call_args_list[1]
    retry_call = run.call_args_list[2]

    assert first_call.args[0] == [
        "git", "worktree", "remove", "--force", "-f", str(wt),
    ]
    assert unlock_call.args[0] == ["git", "worktree", "unlock", str(wt)]
    assert retry_call.args[0] == [
        "git", "worktree", "remove", "--force", str(wt),
    ]


# ---------------------------------------------------------------------------
# (c) already-removed: no subprocess.run at all
# ---------------------------------------------------------------------------
def test_path_missing_returns_silently(tmp_path):
    wt = tmp_path / "does-not-exist"
    # Sanity: tmp_path subdir we never created should not exist.
    assert not wt.exists()

    with patch("cleanup_worker_worktree.subprocess.run") as run:
        cleanup_worker_worktree(wt)

    run.assert_not_called()


# ---------------------------------------------------------------------------
# (d) retry-path log written when decisions_log provided
# ---------------------------------------------------------------------------
def test_retry_path_appends_to_decisions_log(tmp_path):
    wt = tmp_path / "worker-d"
    wt.mkdir()
    log = tmp_path / "decisions.md"

    with patch("cleanup_worker_worktree.subprocess.run") as run:
        run.side_effect = [
            _lock_held_error(str(wt)),
            _ok(),
            _ok(),
        ]
        cleanup_worker_worktree(wt, decisions_log=log)

    assert log.exists()
    contents = log.read_text()
    assert "[tp-run-full-design/tier-3.5] worktree-cleanup-retry" in contents
    assert str(wt) in contents


# ---------------------------------------------------------------------------
# (e) retry-path log silent when decisions_log is None (default)
# ---------------------------------------------------------------------------
def test_retry_path_default_no_log(tmp_path):
    wt = tmp_path / "worker-e"
    wt.mkdir()

    # No log file created beforehand.
    with patch("cleanup_worker_worktree.subprocess.run") as run:
        run.side_effect = [
            _lock_held_error(str(wt)),
            _ok(),
            _ok(),
        ]
        cleanup_worker_worktree(wt)

    # No stray decisions log files in tmp_path.
    leftover = [p for p in tmp_path.iterdir() if p.name == "decisions.md"]
    assert leftover == []
