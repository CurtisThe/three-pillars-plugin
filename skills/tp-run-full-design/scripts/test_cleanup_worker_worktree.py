"""Tests for cleanup_worker_worktree helper.

Covers:
  (a) not-locked happy path: `git worktree list` then `remove --force -f`,
      no decisions.md line.
  (b) locked path: list reports `locked`, remove --force -f, and the OQ5 audit
      line is appended when decisions_log is provided.
  (c) already-removed: no subprocess call when the path is missing.
  (d) locked but decisions_log is None (default): removed, no log file written.
  (e) a non-lock removal failure propagates (CalledProcessError).
  (f) double-force generalizes to any tier worktree path.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cleanup_worker_worktree import _LOG_PREFIX, cleanup_worker_worktree


def _porcelain(worktree: Path, locked: bool) -> str:
    """A `git worktree list --porcelain` block for one worktree."""
    lines = [
        f"worktree {worktree}",
        "HEAD 0000000000000000000000000000000000000000",
        "branch refs/heads/candidate",
    ]
    if locked:
        lines.append("locked claude agent")
    return "\n".join(lines) + "\n"


def _runner(porcelain_text: str, remove_exc: Exception | None = None):
    """subprocess.run side-effect: `list` -> porcelain (text), `remove` -> ok/raise."""
    def run(cmd, **kwargs):
        if cmd[:3] == ["git", "worktree", "list"]:
            r = MagicMock()
            r.returncode = 0
            r.stdout = porcelain_text  # text=True path returns str
            r.stderr = ""
            return r
        if cmd[:3] == ["git", "worktree", "remove"]:
            if remove_exc is not None:
                raise remove_exc
            r = MagicMock()
            r.returncode = 0
            r.stdout = b""
            r.stderr = b""
            return r
        raise AssertionError(f"unexpected command: {cmd}")
    return run


# ---------------------------------------------------------------------------
# (a) not-locked happy path
# ---------------------------------------------------------------------------
def test_unlocked_removes_without_log(tmp_path):
    wt = tmp_path / "worker-1"
    wt.mkdir()
    log = tmp_path / "decisions.md"

    with patch(
        "cleanup_worker_worktree.subprocess.run",
        side_effect=_runner(_porcelain(wt, locked=False)),
    ) as run:
        cleanup_worker_worktree(wt, decisions_log=log)

    cmds = [c.args[0] for c in run.call_args_list]
    assert any(cmd[:4] == ["git", "worktree", "list", "--porcelain"] for cmd in cmds), cmds
    assert any(cmd[:5] == ["git", "worktree", "remove", "--force", "-f"] for cmd in cmds), cmds
    assert not log.exists(), "no audit line should be written when the worktree was not locked"


# ---------------------------------------------------------------------------
# (b) locked path: remove + audit line
# ---------------------------------------------------------------------------
def test_locked_removes_and_logs(tmp_path):
    wt = tmp_path / "worker-2"
    wt.mkdir()
    log = tmp_path / "decisions.md"

    with patch(
        "cleanup_worker_worktree.subprocess.run",
        side_effect=_runner(_porcelain(wt, locked=True)),
    ) as run:
        cleanup_worker_worktree(wt, decisions_log=log)

    cmds = [c.args[0] for c in run.call_args_list]
    assert any(cmd[:5] == ["git", "worktree", "remove", "--force", "-f"] for cmd in cmds), cmds
    assert log.exists()
    contents = log.read_text()
    assert _LOG_PREFIX in contents
    assert str(wt) in contents


# ---------------------------------------------------------------------------
# (c) already-removed: no subprocess.run at all
# ---------------------------------------------------------------------------
def test_path_missing_returns_silently(tmp_path):
    wt = tmp_path / "does-not-exist"
    assert not wt.exists()

    with patch("cleanup_worker_worktree.subprocess.run") as run:
        cleanup_worker_worktree(wt)

    run.assert_not_called()


# ---------------------------------------------------------------------------
# (d) locked but decisions_log is None (default): no log written
# ---------------------------------------------------------------------------
def test_locked_default_no_log(tmp_path):
    wt = tmp_path / "worker-d"
    wt.mkdir()

    with patch(
        "cleanup_worker_worktree.subprocess.run",
        side_effect=_runner(_porcelain(wt, locked=True)),
    ):
        cleanup_worker_worktree(wt)

    leftover = [p for p in tmp_path.iterdir() if p.name == "decisions.md"]
    assert leftover == []


# ---------------------------------------------------------------------------
# (e) a non-lock removal failure propagates
# ---------------------------------------------------------------------------
def test_remove_failure_propagates(tmp_path):
    wt = tmp_path / "worker-e"
    wt.mkdir()
    err = subprocess.CalledProcessError(
        returncode=128,
        cmd=["git", "worktree", "remove", "--force", "-f", str(wt)],
    )
    err.stderr = b"fatal: some other, non-lock failure"

    with patch(
        "cleanup_worker_worktree.subprocess.run",
        side_effect=_runner(_porcelain(wt, locked=False), remove_exc=err),
    ):
        with pytest.raises(subprocess.CalledProcessError):
            cleanup_worker_worktree(wt)


# ---------------------------------------------------------------------------
# (f) the lock query is advisory + fail-open: if `git worktree list` fails,
#     cleanup must still force-remove the worktree (double-force removes a
#     locked one outright anyway) and simply skip the audit line. A failing
#     lock query must NOT abort cleanup.
# ---------------------------------------------------------------------------
def test_list_failure_is_advisory_still_removes(tmp_path):
    wt = tmp_path / "worker-f"
    wt.mkdir()
    log = tmp_path / "decisions.md"

    def run(cmd, **kwargs):
        if cmd[:3] == ["git", "worktree", "list"]:
            raise subprocess.CalledProcessError(
                returncode=128, cmd=cmd, stderr=b"fatal: not a git repository"
            )
        if cmd[:3] == ["git", "worktree", "remove"]:
            r = MagicMock()
            r.returncode = 0
            r.stdout = b""
            r.stderr = b""
            return r
        raise AssertionError(f"unexpected command: {cmd}")

    # Must NOT raise even though the lock query failed.
    with patch("cleanup_worker_worktree.subprocess.run", side_effect=run) as runmock:
        cleanup_worker_worktree(wt, decisions_log=log)

    cmds = [c.args[0] for c in runmock.call_args_list]
    assert any(cmd[:5] == ["git", "worktree", "remove", "--force", "-f"] for cmd in cmds), cmds
    assert not log.exists(), "undetermined lock state -> no audit line, but removal still happened"
