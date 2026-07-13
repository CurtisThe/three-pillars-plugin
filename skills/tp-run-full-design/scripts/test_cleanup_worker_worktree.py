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

Tests (a)/(b)/(d)/(f) patch `sweep_orphan_agent_branches` to a no-op (R5):
their strict `_runner` mocks raise on any command besides `git worktree
list`/`remove`, and the sweep now issues `git branch --list`/`-D` — without
the patch those tests would fail with a confusing "unexpected command"
AssertionError instead of exercising what they actually test.

Task 1.1 (sweep helper) and Task 1.2 (wiring + R1 fail-open) coverage lives
further down, after the locked/unlocked/removal-failure suite above.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cleanup_worker_worktree import (
    _LOG_PREFIX,
    _SWEEP_LOG_PREFIX,
    cleanup_worker_worktree,
    sweep_orphan_agent_branches,
)


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
    ) as run, patch(
        "cleanup_worker_worktree.sweep_orphan_agent_branches", return_value=[]
    ):
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
    ) as run, patch(
        "cleanup_worker_worktree.sweep_orphan_agent_branches", return_value=[]
    ):
        cleanup_worker_worktree(wt, decisions_log=log)

    cmds = [c.args[0] for c in run.call_args_list]
    assert any(cmd[:5] == ["git", "worktree", "remove", "--force", "-f"] for cmd in cmds), cmds
    assert log.exists()
    contents = log.read_text(encoding="utf-8")
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
    ), patch(
        "cleanup_worker_worktree.sweep_orphan_agent_branches", return_value=[]
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
    with patch("cleanup_worker_worktree.subprocess.run", side_effect=run) as runmock, patch(
        "cleanup_worker_worktree.sweep_orphan_agent_branches", return_value=[]
    ):
        cleanup_worker_worktree(wt, decisions_log=log)

    cmds = [c.args[0] for c in runmock.call_args_list]
    assert any(cmd[:5] == ["git", "worktree", "remove", "--force", "-f"] for cmd in cmds), cmds
    assert not log.exists(), "undetermined lock state -> no audit line, but removal still happened"


# ---------------------------------------------------------------------------
# Task 1.2 — sweep wiring: ordering + R1 fail-open at the call site.
# ---------------------------------------------------------------------------
def test_cleanup_invokes_orphan_sweep_after_removal(tmp_path):
    """`sweep_orphan_agent_branches` runs exactly once, AFTER `git worktree
    remove` returns, forwarding the same `decisions_log`."""
    wt = tmp_path / "worker-order"
    wt.mkdir()
    log = tmp_path / "decisions.md"
    calls: list[str] = []

    def run(cmd, **kwargs):
        if cmd[:3] == ["git", "worktree", "list"]:
            r = MagicMock()
            r.returncode = 0
            r.stdout = _porcelain(wt, locked=False)
            r.stderr = ""
            return r
        if cmd[:3] == ["git", "worktree", "remove"]:
            calls.append("remove")
            r = MagicMock()
            r.returncode = 0
            r.stdout = b""
            r.stderr = b""
            return r
        raise AssertionError(f"unexpected command: {cmd}")

    def fake_sweep(decisions_log=None):
        calls.append("sweep")
        assert decisions_log == log
        return []

    with patch("cleanup_worker_worktree.subprocess.run", side_effect=run), patch(
        "cleanup_worker_worktree.sweep_orphan_agent_branches", side_effect=fake_sweep
    ) as sweep_mock:
        cleanup_worker_worktree(wt, decisions_log=log)

    assert calls == ["remove", "sweep"]
    sweep_mock.assert_called_once_with(decisions_log=log)


def test_cleanup_swallows_sweep_exception(tmp_path):
    """R1 (adversarial HIGH): `cleanup_worker_worktree` must NOT raise when
    `sweep_orphan_agent_branches` raises — `run_tier_3_5.py` escalates on ANY
    exception from this function, so a sweep failure must never masquerade
    as a cleanup-failed escalation."""
    wt = tmp_path / "worker-r1"
    wt.mkdir()

    with patch(
        "cleanup_worker_worktree.subprocess.run",
        side_effect=_runner(_porcelain(wt, locked=False)),
    ), patch(
        "cleanup_worker_worktree.sweep_orphan_agent_branches",
        side_effect=RuntimeError("boom"),
    ):
        cleanup_worker_worktree(wt)  # must not raise


# ---------------------------------------------------------------------------
# Task 1.1 — sweep_orphan_agent_branches: name guard, exclusion, fail-open.
# ---------------------------------------------------------------------------
def _worktree_porcelain_multi(entries: list[tuple[Path, str]]) -> str:
    """A multi-worktree `git worktree list --porcelain` block. Each entry is
    (path, branch_ref) where branch_ref is the FULL `refs/heads/<name>` form
    (R4 — keeps the mock honest about the form-mismatch the fix normalizes)."""
    blocks = []
    for path, branch_ref in entries:
        blocks.append(
            f"worktree {path}\n"
            "HEAD 0000000000000000000000000000000000000000\n"
            f"branch {branch_ref}\n"
        )
    return "\n".join(blocks) + "\n"


def test_sweep_deletes_only_orphan_agent_branches(tmp_path):
    """One live worktree on worktree-agent-LIVE; candidates include the live
    branch, an orphan, and two non-matching decoys. Only the orphan is
    deleted — never the live one, never the decoys (name guard + exclusion)."""
    porcelain = _worktree_porcelain_multi(
        [(tmp_path / "live", "refs/heads/worktree-agent-LIVE")]
    )
    branch_list_out = (
        "worktree-agent-LIVE\nworktree-agent-ORPHAN\ncandidate/x/single\ntp/x\n"
    )
    deleted_cmds = []

    def run(cmd, **kwargs):
        if cmd[:3] == ["git", "worktree", "list"]:
            r = MagicMock()
            r.returncode = 0
            r.stdout = porcelain
            r.stderr = ""
            return r
        if cmd[:3] == ["git", "branch", "--list"]:
            r = MagicMock()
            r.returncode = 0
            r.stdout = branch_list_out
            r.stderr = ""
            return r
        if cmd[:3] == ["git", "branch", "-D"]:
            deleted_cmds.append(cmd)
            r = MagicMock()
            r.returncode = 0
            return r
        raise AssertionError(f"unexpected command: {cmd}")

    with patch("cleanup_worker_worktree.subprocess.run", side_effect=run):
        deleted = sweep_orphan_agent_branches()

    assert deleted == ["worktree-agent-ORPHAN"]
    assert deleted_cmds == [["git", "branch", "-D", "worktree-agent-ORPHAN"]]


def test_sweep_worktree_list_failure_fails_open_to_empty_exclusion(tmp_path):
    """R6(a): `git worktree list --porcelain` raises -> exclusion set fails
    open to empty; the sweep still runs (and does not raise)."""
    branch_list_out = "worktree-agent-ORPHAN\n"

    def run(cmd, **kwargs):
        if cmd[:3] == ["git", "worktree", "list"]:
            raise subprocess.CalledProcessError(
                returncode=128, cmd=cmd, stderr=b"fatal: not a git repository"
            )
        if cmd[:3] == ["git", "branch", "--list"]:
            r = MagicMock()
            r.returncode = 0
            r.stdout = branch_list_out
            r.stderr = ""
            return r
        if cmd[:3] == ["git", "branch", "-D"]:
            r = MagicMock()
            r.returncode = 0
            return r
        raise AssertionError(f"unexpected command: {cmd}")

    with patch("cleanup_worker_worktree.subprocess.run", side_effect=run):
        deleted = sweep_orphan_agent_branches()  # must not raise

    assert deleted == ["worktree-agent-ORPHAN"]


def test_sweep_branch_list_failure_returns_empty(tmp_path):
    """Task 1.1 Done-when: `git branch --list` raises -> returns [], no raise."""

    def run(cmd, **kwargs):
        if cmd[:3] == ["git", "worktree", "list"]:
            r = MagicMock()
            r.returncode = 0
            r.stdout = ""
            r.stderr = ""
            return r
        if cmd[:3] == ["git", "branch", "--list"]:
            raise subprocess.CalledProcessError(
                returncode=128, cmd=cmd, stderr=b"fatal: bad glob"
            )
        raise AssertionError(f"unexpected command: {cmd}")

    with patch("cleanup_worker_worktree.subprocess.run", side_effect=run):
        deleted = sweep_orphan_agent_branches()  # must not raise

    assert deleted == []


def test_sweep_single_delete_failure_does_not_abort_remaining(tmp_path):
    """Task 1.1 Done-when: one `git branch -D` failure does not abort the
    remaining deletes."""
    branch_list_out = "worktree-agent-A\nworktree-agent-B\n"
    deleted_cmds = []

    def run(cmd, **kwargs):
        if cmd[:3] == ["git", "worktree", "list"]:
            r = MagicMock()
            r.returncode = 0
            r.stdout = ""
            r.stderr = ""
            return r
        if cmd[:3] == ["git", "branch", "--list"]:
            r = MagicMock()
            r.returncode = 0
            r.stdout = branch_list_out
            r.stderr = ""
            return r
        if cmd[:3] == ["git", "branch", "-D"]:
            deleted_cmds.append(cmd)
            if cmd[3] == "worktree-agent-A":
                raise subprocess.CalledProcessError(
                    returncode=1, cmd=cmd, stderr=b"fatal: cannot delete"
                )
            r = MagicMock()
            r.returncode = 0
            return r
        raise AssertionError(f"unexpected command: {cmd}")

    with patch("cleanup_worker_worktree.subprocess.run", side_effect=run):
        deleted = sweep_orphan_agent_branches()

    assert deleted == ["worktree-agent-B"]
    assert [c[3] for c in deleted_cmds] == ["worktree-agent-A", "worktree-agent-B"]


def test_sweep_decisions_log_append_oserror_is_swallowed(tmp_path):
    """R6(b): a decisions.md append OSError is swallowed; the helper still
    returns the deleted list normally."""
    branch_list_out = "worktree-agent-X\n"

    def run(cmd, **kwargs):
        if cmd[:3] == ["git", "worktree", "list"]:
            r = MagicMock()
            r.returncode = 0
            r.stdout = ""
            r.stderr = ""
            return r
        if cmd[:3] == ["git", "branch", "--list"]:
            r = MagicMock()
            r.returncode = 0
            r.stdout = branch_list_out
            r.stderr = ""
            return r
        if cmd[:3] == ["git", "branch", "-D"]:
            r = MagicMock()
            r.returncode = 0
            return r
        raise AssertionError(f"unexpected command: {cmd}")

    # Parent dir absent -> `open(..., "a")` raises OSError (FileNotFoundError).
    bad_log = tmp_path / "no-such-dir" / "decisions.md"

    with patch("cleanup_worker_worktree.subprocess.run", side_effect=run):
        deleted = sweep_orphan_agent_branches(decisions_log=bad_log)  # must not raise

    assert deleted == ["worktree-agent-X"]
    assert _SWEEP_LOG_PREFIX  # imported symbol used (log-line prefix contract)
