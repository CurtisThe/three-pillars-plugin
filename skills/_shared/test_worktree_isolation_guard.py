"""Tests for worktree_isolation_guard.py — the worker isolation predicate.

Tests drive the predicate via override flags (--cwd, --worktree-porcelain,
--dispatch-sha, --return-sha) so no real git state is needed.

Run with: python -m pytest skills/_shared/test_worktree_isolation_guard.py -q

Design refs:
  - three-pillars-docs/completed-tp-designs/fleet-worktree-isolation-guards/detailed-design.md
  - three-pillars-docs/completed-tp-designs/fleet-worktree-isolation-guards/plan.md
"""

from __future__ import annotations

import io
import subprocess
import sys
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

import pytest

import worktree_isolation_guard
from worktree_isolation_guard import (
    live_tp_worktrees,
    is_shared_with_orchestrator,
    assert_own_worktree,
    forbid_checkout_in_shared,
    head_drift,
    main,
    orchestration_only_staged,
)


# ---------------------------------------------------------------------------
# Porcelain fixture helpers
# ---------------------------------------------------------------------------

_PORCELAIN_MASTER_AND_TP = """\
worktree /home/user/repo
HEAD abc123
branch refs/heads/master

worktree /home/user/repo-wt/a
HEAD def456
branch refs/heads/tp/a

worktree /home/user/repo-wt/b
HEAD ghi789
branch refs/heads/tp/b

"""

_PORCELAIN_MASTER_ONLY = """\
worktree /home/user/repo
HEAD abc123
branch refs/heads/master

"""

_PORCELAIN_WITH_TP_X = """\
worktree /home/user/repo
HEAD abc123
branch refs/heads/master

worktree /home/user/repo-wt/x
HEAD def456
branch refs/heads/tp/x

"""

_PORCELAIN_WITH_CANDIDATE = """\
worktree /home/user/repo
HEAD abc123
branch refs/heads/master

worktree /home/user/repo/.claude/worktrees/agent-abc123
HEAD def456
branch refs/heads/candidate/my-design/single

worktree /home/user/repo-wt/x
HEAD ghi789
branch refs/heads/tp/x

"""


def _run_main(args):
    """Call main(argv) and return (return_code, stderr_output)."""
    buf = io.StringIO()
    with redirect_stderr(buf):
        rc = main(args)
    return rc, buf.getvalue()


# ---------------------------------------------------------------------------
# Task 1.1: live_tp_worktrees — returns (toplevel, branch) tuples
# ---------------------------------------------------------------------------


def test_live_tp_worktrees_mixed():
    result = live_tp_worktrees(_PORCELAIN_MASTER_AND_TP)
    assert result == [
        ("/home/user/repo-wt/a", "tp/a"),
        ("/home/user/repo-wt/b", "tp/b"),
    ]


def test_live_tp_worktrees_master_only():
    result = live_tp_worktrees(_PORCELAIN_MASTER_ONLY)
    assert result == []


def test_live_tp_worktrees_single_tp():
    result = live_tp_worktrees(_PORCELAIN_WITH_TP_X)
    assert result == [("/home/user/repo-wt/x", "tp/x")]


def test_live_tp_worktrees_includes_toplevel_path():
    """Assert we capture (path, branch) not just branch."""
    result = live_tp_worktrees(_PORCELAIN_MASTER_AND_TP)
    paths = [p for p, _ in result]
    branches = [b for _, b in result]
    assert "/home/user/repo-wt/a" in paths
    assert "/home/user/repo-wt/b" in paths
    assert "tp/a" in branches
    assert "tp/b" in branches


def test_live_tp_worktrees_candidate_branch_not_included():
    """candidate/* branches are NOT tp/* — must not appear in result."""
    result = live_tp_worktrees(_PORCELAIN_WITH_CANDIDATE)
    branches = [b for _, b in result]
    assert not any(b.startswith("candidate/") for b in branches)
    assert ("tp/x", ) == tuple(b for b in branches)


# ---------------------------------------------------------------------------
# Task 1.2: is_shared_with_orchestrator containment helper
# ---------------------------------------------------------------------------


def test_is_shared_equal_to_toplevel_is_inside():
    """cwd exactly equal to the worktree toplevel → IS inside own worktree (not shared)."""
    result = is_shared_with_orchestrator(
        cwd="/home/user/repo-wt/x",
        worktree_toplevel="/home/user/repo-wt/x",
    )
    assert result is False  # cwd IS inside the tp worktree → not shared


def test_is_shared_subdir_of_toplevel_is_inside():
    """cwd under the worktree toplevel → IS inside own worktree."""
    result = is_shared_with_orchestrator(
        cwd="/home/user/repo-wt/x/skills/_shared",
        worktree_toplevel="/home/user/repo-wt/x",
    )
    assert result is False


def test_is_shared_outside_toplevel_is_shared():
    """cwd NOT inside any tp toplevel → IS sharing the orchestrator worktree."""
    result = is_shared_with_orchestrator(
        cwd="/home/user/repo",
        worktree_toplevel="/home/user/repo-wt/x",
    )
    assert result is True


def test_is_shared_sibling_worktree_is_shared():
    """cwd in a DIFFERENT tp worktree than the given toplevel → shared (not own)."""
    result = is_shared_with_orchestrator(
        cwd="/home/user/repo-wt/y",
        worktree_toplevel="/home/user/repo-wt/x",
    )
    assert result is True


# ---------------------------------------------------------------------------
# Task 1.3: assert_own_worktree — the invariant-#31 predicate
# Three required truth-table cases per the CRITICAL CORRECTNESS REQUIREMENT:
# PASS (orchestrator artifact commit), PASS (worker in own worktree), BLOCK (corruption)
# ---------------------------------------------------------------------------


def test_assert_own_worktree_pass_orchestrator_artifact_commit():
    """PASS (orchestrator artifact commit): cwd is inside a live tp/<slug> worktree
    AND HEAD is on that worktree's tp/<slug> branch.

    This is the orchestrator writing design artifacts — legitimate; blocking it
    would deadlock the pipeline, INCLUDING the fold/archive commits onto tp/<slug>.
    """
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo-wt/x",
        worktree_porcelain=_PORCELAIN_WITH_TP_X,
        current_branch="tp/x",  # HEAD == tp/<slug> branch for this worktree
    )
    assert ok is True
    assert msg == ""


def test_assert_own_worktree_pass_worker_in_own_worktree():
    """PASS (worker commit in own worktree): cwd is a .claude/worktrees/agent-* worktree
    (NOT inside any tp/<slug> toplevel) with a candidate/* branch.

    This is the worker operating in its own isolated space — legitimate.
    The cwd is outside all tp/* toplevels, so this is case (2): not-in-any-tp → PASS.
    """
    # Real multi-worktree porcelain: tp/* worktrees exist, but cwd is agent-*
    porcelain_with_tp_and_agent = """\
worktree /home/user/repo
HEAD abc123
branch refs/heads/master

worktree /home/user/repo-wt/x
HEAD ghi789
branch refs/heads/tp/x

worktree /home/user/repo/.claude/worktrees/agent-abc
HEAD def456
branch refs/heads/candidate/my-design/single

"""
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo/.claude/worktrees/agent-abc",
        worktree_porcelain=porcelain_with_tp_and_agent,
        current_branch="candidate/my-design/single",
    )
    assert ok is True
    assert msg == ""


def test_assert_own_worktree_block_corruption_case():
    """BLOCK (corruption case): cwd is inside a live tp/<slug> worktree but HEAD
    has drifted to a candidate/* branch — a worker checked out the candidate
    INSIDE the shared orchestrator worktree.

    This is the exact incident class this design guards against (M13/M14).
    """
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo-wt/x",       # cwd IS the tp/x worktree
        worktree_porcelain=_PORCELAIN_WITH_TP_X,
        current_branch="candidate/my-design/single",  # HEAD drifted to candidate/*
    )
    assert ok is False
    assert msg
    assert "candidate" in msg.lower() or "foreign" in msg.lower() or "tp/x" in msg


def test_assert_own_worktree_block_shared_orchestrator_root():
    """BLOCK (review blocking #2 — the M14 headline): a commit from the shared
    default-branch (master) orchestrator worktree root while tp/* worktrees are
    live MUST fail-closed.

    This is the exact scenario the prior predicate failed OPEN on (case-2
    PASS-allowed any cwd outside all tp toplevels, collapsing the shared root in
    with legitimate agent worktrees). The guard must now BLOCK."""
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo",            # the shared master/orchestrator root
        worktree_porcelain=_PORCELAIN_WITH_TP_X,  # tp/x is live
        current_branch="master",
    )
    assert ok is False, "commit from shared master root with live tp/* must BLOCK"
    assert msg
    assert "master" in msg.lower() or "shared" in msg.lower()


def test_assert_own_worktree_block_shared_root_multiple_tp():
    """BLOCK: shared master root commit while MULTIPLE tp/* worktrees are live."""
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo",
        worktree_porcelain=_PORCELAIN_MASTER_AND_TP,  # tp/a + tp/b live
        current_branch="master",
    )
    assert ok is False
    assert msg


def test_assert_own_worktree_block_shared_root_branch_self_read():
    """BLOCK even when current_branch override is omitted (the live framework-check
    invocation form: cwd + porcelain self-read from the same HEAD).

    framework-check.sh calls the guard with --repo only; the master root's
    porcelain branch is 'master', so the default-branch BLOCK fires off the
    porcelain branch with no explicit override."""
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo",
        worktree_porcelain=_PORCELAIN_WITH_TP_X,
        current_branch="",  # no override → porcelain reports master at this path
    )
    assert ok is False, "shared-root BLOCK must fire from porcelain branch when no override"
    assert msg


def test_assert_own_worktree_pass_when_no_live_tp():
    """PASS (empty-live short-circuit): no tp/* worktree is live."""
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo",
        worktree_porcelain=_PORCELAIN_MASTER_ONLY,
    )
    assert ok is True
    assert msg == ""


def test_assert_own_worktree_block_msg_names_hazard():
    """Blocking message must name the hazard and the live worktree."""
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo-wt/x",
        worktree_porcelain=_PORCELAIN_WITH_TP_X,
        current_branch="candidate/some-design/single",
    )
    assert not ok
    assert "tp/x" in msg or "/repo-wt/x" in msg  # names the live worktree
    assert "shared" in msg.lower() or "foreign" in msg.lower() or "candidate" in msg.lower()


def test_assert_own_worktree_pass_when_cwd_inside_subdir_of_tp_on_own_branch():
    """PASS: cwd is a subdir of a live tp worktree AND on the correct tp branch."""
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo-wt/x/skills/_shared",
        worktree_porcelain=_PORCELAIN_WITH_TP_X,
        current_branch="tp/x",
    )
    assert ok is True
    assert msg == ""


def test_assert_own_worktree_pass_with_multiple_tp_worktrees_in_own():
    """PASS: cwd is inside one of multiple live tp worktrees, on matching branch."""
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo-wt/a",
        worktree_porcelain=_PORCELAIN_MASTER_AND_TP,
        current_branch="tp/a",
    )
    assert ok is True
    assert msg == ""


def test_assert_own_worktree_block_with_multiple_tp_worktrees_and_wrong_branch():
    """BLOCK: cwd inside a tp/* worktree but HEAD is on candidate/* branch."""
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo-wt/a",
        worktree_porcelain=_PORCELAIN_MASTER_AND_TP,
        current_branch="candidate/some/single",
    )
    assert ok is False
    assert msg


def test_assert_own_worktree_agent_worktree_with_live_tp_passes():
    """PASS: worker commit from agent worktree while multiple tp/* worktrees are live.

    The agent cwd is NOT inside any tp/<slug> toplevel → case (2) → PASS.
    This is the real scenario: an agent worktree on candidate/* branch, while the
    orchestrator's tp/* worktrees are live.
    """
    porcelain_with_tp_and_agent = """\
worktree /home/user/repo
HEAD abc123
branch refs/heads/master

worktree /home/user/repo-wt/fleet-guard
HEAD ghi789
branch refs/heads/tp/fleet-guard

worktree /home/user/repo-wt/another-design
HEAD jkl012
branch refs/heads/tp/another-design

worktree /home/user/repo/.claude/worktrees/agent-a76ffcf4
HEAD def456
branch refs/heads/candidate/fleet-guard/single

"""
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo/.claude/worktrees/agent-a76ffcf4",
        worktree_porcelain=porcelain_with_tp_and_agent,
        current_branch="candidate/fleet-guard/single",
    )
    assert ok is True
    assert msg == ""


def test_assert_own_worktree_no_branch_cwd_outside_tp_passes():
    """PASS: cwd NOT in any tp/* worktree, current_branch empty → case (2) → PASS."""
    ok, msg = assert_own_worktree(
        cwd="/home/user/other-place",
        worktree_porcelain=_PORCELAIN_WITH_TP_X,
        current_branch="",
    )
    assert ok is True
    assert msg == ""


def test_assert_own_worktree_no_branch_cwd_inside_tp_on_its_branch_passes():
    """PASS: cwd inside a tp worktree, current_branch override empty, but the
    porcelain authoritatively reports the worktree on its tp/<slug> branch.

    The expected branch is derived from the worktree PATH; the porcelain branch
    is the authoritative fallback when no explicit current_branch override is
    given. Since porcelain says tp/x and the path slug is x, they agree → PASS.
    (The fail-closed HEAD-drift case is covered by the porcelain-drift test
    below, where the porcelain itself reports a foreign branch.)
    """
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo-wt/x",
        worktree_porcelain=_PORCELAIN_WITH_TP_X,
        current_branch="",  # no override → fall back to porcelain (tp/x)
    )
    assert ok is True
    assert msg == ""


def test_assert_own_worktree_tp_worktree_porcelain_reports_drift_blocks():
    """BLOCK (HEAD drift, review blocking #3): the porcelain itself reports the
    tp-provisioned worktree '/home/user/repo-wt/x' on a foreign candidate/*
    branch (so it drops out of `live`), and a commit is attempted from inside it.

    The expected branch is derived from the worktree PATH (tp/x), independent of
    the drifted HEAD, so the guard still BLOCKs even though the worktree no longer
    appears as a live tp/* entry. This is the exact M14 HEAD-drift incident."""
    porcelain_drifted = """\
worktree /home/user/repo
HEAD abc123
branch refs/heads/master

worktree /home/user/repo-wt/x
HEAD def456
branch refs/heads/candidate/my-design/single

worktree /home/user/repo-wt/y
HEAD ghi789
branch refs/heads/tp/y

"""
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo-wt/x",       # the drifted tp-provisioned worktree
        worktree_porcelain=porcelain_drifted,
        current_branch="",                # no override → porcelain (candidate/*)
    )
    assert ok is False
    assert msg
    assert "tp/x" in msg  # names the expected branch derived from the path


# Single drifted tp worktree (no sibling keeping `live` non-empty) — the
# porcelain has exactly ONE provisioned -wt/<slug> worktree and it has drifted to
# candidate/*, so `live` is EMPTY. This is the canonical M14 incident: one design,
# the sole worker checks out candidate/* inside its own tp/<slug> worktree.
_PORCELAIN_SINGLE_DRIFTED = """\
worktree /home/user/repo
HEAD abc123
branch refs/heads/master

worktree /home/user/repo-wt/x
HEAD def456
branch refs/heads/candidate/my-design/single

"""


def test_assert_own_worktree_single_drifted_tp_blocks():
    """BLOCK (M14 single-drift hole): the SOLE provisioned tp worktree has drifted
    to candidate/*, so `live` is EMPTY. The empty-live short-circuit must NOT skip
    the path-derived HEAD-drift BLOCK — committing from inside the drifted
    worktree must still fail-closed.

    This is the regression that the prior fixture (with a tp/y sibling keeping
    `live` non-empty) masked. With no sibling, `live` is empty and the old
    short-circuit let it PASS — the new predicate BLOCKs off the provisioned-path
    attribution instead."""
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo-wt/x",       # the sole drifted tp-provisioned worktree
        worktree_porcelain=_PORCELAIN_SINGLE_DRIFTED,
        current_branch="",                # no override → porcelain (candidate/*)
    )
    assert ok is False, "sole drifted tp worktree (empty live) must BLOCK, not PASS"
    assert msg
    assert "tp/x" in msg  # names the expected branch derived from the path


def test_assert_own_worktree_single_drifted_master_root_commit_blocks():
    """BLOCK (M14 single-drift, master-root variant): a commit from the shared
    master/orchestrator root while the SOLE provisioned tp worktree has drifted to
    candidate/* (so `live` is EMPTY) must STILL fail-closed.

    The same empty-live hole let a master-root commit pass when the sole tp
    worktree dropped out of `live`. The provisioned-path set keeps the
    default-branch BLOCK armed."""
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo",            # the shared master/orchestrator root
        worktree_porcelain=_PORCELAIN_SINGLE_DRIFTED,
        current_branch="master",
    )
    assert ok is False, "master-root commit with sole drifted tp worktree must BLOCK"
    assert msg
    assert "master" in msg.lower() or "shared" in msg.lower()


def test_assert_own_worktree_drift_blocks_even_without_sibling():
    """Predicate-not-fixture proof: take the existing drift fixture and REMOVE the
    tp/y sibling that kept `live` non-empty. With only the drifted tp/x worktree
    present (empty live), the guard must STILL BLOCK — proving the BLOCK is driven
    by the path-derived expected branch, not by the incidental live sibling."""
    porcelain_no_sibling = """\
worktree /home/user/repo
HEAD abc123
branch refs/heads/master

worktree /home/user/repo-wt/x
HEAD def456
branch refs/heads/candidate/my-design/single

"""
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo-wt/x",
        worktree_porcelain=porcelain_no_sibling,
        current_branch="",
    )
    assert ok is False, "drift BLOCK must survive removal of the live sibling"
    assert "tp/x" in msg


# ---------------------------------------------------------------------------
# M14 bare-root coverage: this operator's documented bare-base-checkout topology
# (core.bare=true WITH a live working tree). `git worktree list --porcelain`
# emits a `bare` line and NO `branch refs/heads/master` line for the main
# checkout, so owner_branch parses to "" and the default-branch Case-2 BLOCK
# previously failed OPEN. The fix classifies a `bare` root (and the main-worktree
# path shape) as a default-branch shared-orchestrator seat regardless of how the
# branch is reported. See known-issues M14 and the operator MEMORY note
# ("never assume a (bare)-labeled repo lacks a working tree; verify core.bare").
# ---------------------------------------------------------------------------

# Bare orchestrator root (porcelain `bare` line, NO branch line) + a SOLE tp
# worktree drifted to candidate/* (so `live` is empty).
_PORCELAIN_BARE_ROOT_DRIFTED = """\
worktree /home/user/repo
HEAD abc123
bare

worktree /home/user/repo-wt/x
HEAD def456
branch refs/heads/candidate/my-design/single

"""

# Bare orchestrator root + a HEALTHY live tp worktree.
_PORCELAIN_BARE_ROOT_HEALTHY = """\
worktree /home/user/repo
HEAD abc123
bare

worktree /home/user/repo-wt/x
HEAD def456
branch refs/heads/tp/x

"""

# Bare orchestrator root with NO tp worktrees at all.
_PORCELAIN_BARE_ROOT_ONLY = """\
worktree /home/user/repo
HEAD abc123
bare

"""


def test_all_worktrees_surfaces_bare_flag():
    """all_worktrees() must surface the porcelain `bare` line as is_bare=True.

    Without this the default-branch classifier can't see that the main checkout
    is the bare-base seat (it reports no branch), and the Case-2 BLOCK fails open.
    """
    result = worktree_isolation_guard.all_worktrees(_PORCELAIN_BARE_ROOT_HEALTHY)
    # (toplevel, branch, is_bare)
    assert ("/home/user/repo", "", True) in result
    assert ("/home/user/repo-wt/x", "tp/x", False) in result


def test_assert_own_bare_root_commit_with_drifted_sole_tp_blocks():
    """BLOCK (M14 bare-root hole, scenario 1): a commit from the BARE
    orchestrator root while the SOLE provisioned tp worktree has drifted to
    candidate/* (so `live` is empty) must fail-closed.

    The porcelain marks the root `bare` with NO branch line, so owner_branch is
    "". The default-branch BLOCK must still fire off the `bare` flag — this is
    the exact hole that PASSed before the fix on this operator's bare-base
    topology."""
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo",                       # the bare orchestrator root
        worktree_porcelain=_PORCELAIN_BARE_ROOT_DRIFTED,
        current_branch="",                           # bare root reports no branch
    )
    assert ok is False, "bare-root commit + drifted sole tp must BLOCK, not PASS"
    assert msg
    assert "shared" in msg.lower() or "bare" in msg.lower()


def test_assert_own_bare_root_commit_with_healthy_tp_blocks():
    """BLOCK (M14 bare-root hole, scenario 2): a commit from the BARE
    orchestrator root while a HEALTHY live tp worktree exists must fail-closed.

    Same bare-root attribution as scenario 1 but with a live tp/* worktree —
    both must BLOCK. Previously both PASSed because owner_branch="" was not in
    _DEFAULT_BRANCHES."""
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo",
        worktree_porcelain=_PORCELAIN_BARE_ROOT_HEALTHY,
        current_branch="",
    )
    assert ok is False, "bare-root commit + healthy live tp must BLOCK, not PASS"
    assert msg
    assert "shared" in msg.lower() or "bare" in msg.lower()


def test_assert_own_bare_root_no_tp_worktrees_passes():
    """PASS (no over-block, scenario 3): a bare orchestrator root with NO tp
    worktrees at all must PASS — a genuinely-empty bare/master-only checkout has
    nothing to isolate against (Case-1 empty-live short-circuit)."""
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo",
        worktree_porcelain=_PORCELAIN_BARE_ROOT_ONLY,
        current_branch="",
    )
    assert ok is True, "bare root with no tp worktrees must PASS (no over-block)"
    assert msg == ""


def test_assert_own_healthy_tp_on_own_branch_with_bare_root_passes():
    """PASS (no over-block, scenario 4): a healthy tp worktree committing on its
    own tp/<slug> branch, while the orchestrator root is bare, must PASS."""
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo-wt/x",
        worktree_porcelain=_PORCELAIN_BARE_ROOT_HEALTHY,
        current_branch="tp/x",
    )
    assert ok is True, "healthy tp wt on own branch must PASS even under a bare root"
    assert msg == ""


def test_assert_own_agent_candidate_worktree_with_bare_root_passes():
    """PASS (no over-block, scenario 5): an agent worktree on candidate/* under
    `.claude/worktrees/`, while the orchestrator root is bare and a tp worktree
    is live, must PASS — the agent worktree is its own isolated seat and must NOT
    be misclassified as a default-branch root by the path-shape fallback."""
    porcelain = """\
worktree /home/user/repo
HEAD abc123
bare

worktree /home/user/repo-wt/x
HEAD def456
branch refs/heads/tp/x

worktree /home/user/repo/.claude/worktrees/agent-abc
HEAD ghi789
branch refs/heads/candidate/x/single

"""
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo/.claude/worktrees/agent-abc",
        worktree_porcelain=porcelain,
        current_branch="candidate/x/single",
    )
    assert ok is True, "agent candidate/* worktree must PASS (not a default-branch root)"
    assert msg == ""


def test_assert_own_bare_root_detached_agent_with_bare_root_passes():
    """PASS: a detached-HEAD agent worktree under `.claude/worktrees/` (no branch
    line) must NOT be misclassified as a default-branch root by the path-shape
    fallback — the `.claude/worktrees/` segment excludes it."""
    porcelain = """\
worktree /home/user/repo
HEAD abc123
bare

worktree /home/user/repo-wt/x
HEAD def456
branch refs/heads/tp/x

worktree /home/user/repo/.claude/worktrees/agent-detached
HEAD ghi789
detached

"""
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo/.claude/worktrees/agent-detached",
        worktree_porcelain=porcelain,
        current_branch="",
    )
    assert ok is True, "detached agent worktree must PASS (not a default-branch root)"
    assert msg == ""


# ---------------------------------------------------------------------------
# Task 1.4: forbid_checkout_in_shared boundary helper
# ---------------------------------------------------------------------------


def test_forbid_checkout_in_shared_refuse_when_shared():
    """REFUSE: cwd is shared/non-own while a tp worktree is live."""
    ok, msg = forbid_checkout_in_shared(
        cwd="/home/user/repo",
        worktree_porcelain=_PORCELAIN_WITH_TP_X,
    )
    assert ok is False
    assert msg


def test_forbid_checkout_in_shared_allow_when_in_own():
    """ALLOW: cwd is inside its own tp worktree."""
    ok, msg = forbid_checkout_in_shared(
        cwd="/home/user/repo-wt/x",
        worktree_porcelain=_PORCELAIN_WITH_TP_X,
    )
    assert ok is True
    assert msg == ""


def test_forbid_checkout_in_shared_allow_when_no_tp():
    """ALLOW: no tp worktree is live."""
    ok, msg = forbid_checkout_in_shared(
        cwd="/home/user/repo",
        worktree_porcelain=_PORCELAIN_MASTER_ONLY,
    )
    assert ok is True
    assert msg == ""


def test_forbid_checkout_in_shared_message_names_checkout():
    """Message must distinctly mention 'checkout' (distinguishing it from assert_own)."""
    ok, msg = forbid_checkout_in_shared(
        cwd="/home/user/repo",
        worktree_porcelain=_PORCELAIN_WITH_TP_X,
    )
    assert not ok
    assert "checkout" in msg.lower()


def test_forbid_checkout_message_distinct_from_assert_own():
    """forbid_checkout and assert_own have distinct semantics and messages.

    forbid_checkout: blocks when cwd is OUTSIDE all tp/* worktrees (shared orchestrator),
    using checkout-specific guidance naming the checkout hazard.

    assert_own: blocks when cwd IS inside tp/* but HEAD is on a foreign branch (corruption).

    Both blocking cases must produce messages with distinct wording.
    """
    # forbid_checkout: block case — cwd is outside all tp/* (shared orchestrator)
    ok2, msg2 = forbid_checkout_in_shared(
        cwd="/home/user/repo",  # outside all tp/* worktrees → forbidden
        worktree_porcelain=_PORCELAIN_WITH_TP_X,
    )
    # assert_own: block case — cwd inside tp/* but HEAD is foreign (corruption)
    ok1, msg1 = assert_own_worktree(
        cwd="/home/user/repo-wt/x",
        worktree_porcelain=_PORCELAIN_WITH_TP_X,
        current_branch="candidate/my-design/single",
    )
    assert not ok2  # forbid_checkout blocks
    assert not ok1  # assert_own blocks
    # Messages must be distinct (different wording)
    assert "checkout" in msg2.lower(), "forbid_checkout message must mention 'checkout'"
    assert msg1 != msg2


# ---------------------------------------------------------------------------
# Task 1.5: head_drift pure comparator
# ---------------------------------------------------------------------------


def test_head_drift_equal_shas_no_drift():
    """Equal non-empty SHAs → no drift, ok=True, empty message."""
    ok, msg = head_drift(
        dispatch_sha="abc123def456",
        return_sha="abc123def456",
    )
    assert ok is True
    assert msg == ""


def test_head_drift_different_shas_drift():
    """Differing non-empty SHAs → drift, ok=False, message names both."""
    ok, msg = head_drift(
        dispatch_sha="abc123",
        return_sha="def456",
    )
    assert ok is False
    assert msg
    assert "abc123" in msg
    assert "def456" in msg


def test_head_drift_empty_dispatch_sha_blocks():
    """Empty dispatch_sha → INDETERMINATE-style block (never silent pass)."""
    ok, msg = head_drift(
        dispatch_sha="",
        return_sha="def456",
    )
    assert ok is False
    assert msg


def test_head_drift_empty_return_sha_blocks():
    """Empty return_sha → INDETERMINATE-style block."""
    ok, msg = head_drift(
        dispatch_sha="abc123",
        return_sha="",
    )
    assert ok is False
    assert msg


def test_head_drift_both_empty_blocks():
    """Both empty → INDETERMINATE-style block."""
    ok, msg = head_drift(dispatch_sha="", return_sha="")
    assert ok is False
    assert msg


# ---------------------------------------------------------------------------
# Task 1.6: main CLI exit codes
# ---------------------------------------------------------------------------


def test_main_assert_own_worktree_pass_orchestrator():
    """--assert-own-worktree with cwd in tp worktree AND HEAD on tp branch → exit 0."""
    rc, stderr = _run_main([
        "--assert-own-worktree",
        "--cwd", "/home/user/repo-wt/x",
        "--worktree-porcelain", _PORCELAIN_WITH_TP_X,
        "--branch", "tp/x",  # HEAD == tp/<slug> branch
    ])
    assert rc == 0
    assert not stderr


def test_main_assert_own_worktree_pass_worker():
    """--assert-own-worktree with cwd in agent worktree (not inside any tp) → exit 0."""
    porcelain = """\
worktree /home/user/repo
HEAD abc123
branch refs/heads/master

worktree /home/user/repo-wt/x
HEAD ghi789
branch refs/heads/tp/x

worktree /home/user/repo/.claude/worktrees/agent-abc
HEAD def456
branch refs/heads/candidate/my-design/single

"""
    rc, stderr = _run_main([
        "--assert-own-worktree",
        "--cwd", "/home/user/repo/.claude/worktrees/agent-abc",
        "--worktree-porcelain", porcelain,
        "--branch", "candidate/my-design/single",
    ])
    assert rc == 0
    assert not stderr


def test_main_assert_own_worktree_block_corruption():
    """--assert-own-worktree with cwd in tp worktree but HEAD on candidate/* → exit 1."""
    rc, stderr = _run_main([
        "--assert-own-worktree",
        "--cwd", "/home/user/repo-wt/x",  # cwd IS the tp/x worktree
        "--worktree-porcelain", _PORCELAIN_WITH_TP_X,
        "--branch", "candidate/my-design/single",  # HEAD drifted to candidate/*
    ])
    assert rc == 1
    assert stderr


def test_main_assert_own_worktree_no_live_tp_pass():
    """--assert-own-worktree with no live tp/* → exit 0 (empty-live short-circuit)."""
    rc, stderr = _run_main([
        "--assert-own-worktree",
        "--cwd", "/home/user/repo",
        "--worktree-porcelain", _PORCELAIN_MASTER_ONLY,
    ])
    assert rc == 0
    assert not stderr


def test_main_forbid_checkout_refuse():
    """forbid-checkout with cwd in shared worktree → exit 1."""
    rc, stderr = _run_main([
        "forbid-checkout",
        "--cwd", "/home/user/repo",
        "--worktree-porcelain", _PORCELAIN_WITH_TP_X,
    ])
    assert rc == 1
    assert stderr


def test_main_forbid_checkout_allow():
    """forbid-checkout with cwd in own tp worktree → exit 0."""
    rc, stderr = _run_main([
        "forbid-checkout",
        "--cwd", "/home/user/repo-wt/x",
        "--worktree-porcelain", _PORCELAIN_WITH_TP_X,
    ])
    assert rc == 0
    assert not stderr


def test_main_head_drift_no_drift():
    """head-drift with equal SHAs → exit 0."""
    rc, stderr = _run_main([
        "head-drift",
        "--dispatch-sha", "abc123",
        "--return-sha", "abc123",
    ])
    assert rc == 0
    assert not stderr


def test_main_head_drift_drift():
    """head-drift with differing SHAs → exit 1, guidance on stderr."""
    rc, stderr = _run_main([
        "head-drift",
        "--dispatch-sha", "abc123",
        "--return-sha", "def456",
    ])
    assert rc == 1
    assert stderr


def test_main_head_drift_empty_sha():
    """head-drift with empty SHA → exit 1."""
    rc, stderr = _run_main([
        "head-drift",
        "--dispatch-sha", "",
        "--return-sha", "def456",
    ])
    assert rc == 1
    assert stderr


def test_main_guidance_on_stderr_not_stdout():
    """Blocking guidance must land on stderr, not stdout."""
    buf_out = io.StringIO()
    buf_err = io.StringIO()
    import sys
    old_out = sys.stdout
    old_err = sys.stderr
    sys.stdout = buf_out
    sys.stderr = buf_err
    try:
        rc = main([
            "--assert-own-worktree",
            "--cwd", "/home/user/repo-wt/x",
            "--worktree-porcelain", _PORCELAIN_WITH_TP_X,
            "--branch", "candidate/my-design/single",  # corruption case
        ])
    finally:
        sys.stdout = old_out
        sys.stderr = old_err
    assert rc == 1
    assert not buf_out.getvalue()  # nothing on stdout
    assert buf_err.getvalue()       # guidance on stderr


# ---------------------------------------------------------------------------
# Task 4.1: framework-check invariant #31 smoke test
# ---------------------------------------------------------------------------


def test_framework_check_inv32_wired():
    """Smoke: framework-check.sh has the #32 gate block and bumped footer.

    (Renumbered from #31 to #32 when living-spec-layer's drift-scan invariant #31
    landed alongside this design on master.)"""
    here = Path(__file__).resolve().parent
    fcs_path = here.parent.parent / "framework-check.sh"
    content = fcs_path.read_text(encoding="utf-8")

    # (1) Footer is DERIVED from active_count (invariant-citation-coherence added
    #     inv #38, which made the banner runtime-derived rather than a literal).
    assert "framework-check: all ${_INV_N} invariants passed" in content, (
        "footer must read the derived 'all ${_INV_N} invariants passed' banner"
    )

    # (2) The #32 gate block delegates to worktree_isolation_guard.py
    assert "worktree_isolation_guard.py" in content, (
        "#32 gate block must reference worktree_isolation_guard.py"
    )
    assert "--assert-own-worktree" in content, (
        "#32 gate block must use --assert-own-worktree"
    )

    # (3) Positioned after #29 write-guard block
    idx_29 = content.find("worktree_write_guard.py")
    idx_32 = content.find("worktree_isolation_guard.py")
    assert idx_29 != -1, "#29 write-guard must still be present"
    assert idx_32 != -1, "#32 isolation-guard must be present"
    assert idx_32 > idx_29, "#32 must appear after #29 in the file"


# ---------------------------------------------------------------------------
# Task 4.2: Live-mode short-circuit test
# ---------------------------------------------------------------------------


def test_assert_own_live_mode_short_circuits():
    """With master-only porcelain injected, --assert-own-worktree exits 0.

    This simulates the form framework-check invariant #31 invokes on a checkout
    with no live tp/* worktrees — the empty-live short-circuit must hold so
    framework-check never self-blocks on a master-only / no-worktree checkout.
    """
    rc, stderr = _run_main([
        "--assert-own-worktree",
        "--worktree-porcelain", _PORCELAIN_MASTER_ONLY,
        "--cwd", "/home/user/repo",
        "--branch", "master",
    ])
    assert rc == 0, "empty-live short-circuit must exit 0"
    assert not stderr


# ---------------------------------------------------------------------------
# seat-aware-collaboration-protocol: orchestration paper-trail carve-out tests
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Task 1.1: orchestration_only_staged() helper (design test-matrix rows 1-3)
# ---------------------------------------------------------------------------


def test_orchestration_only_staged_all_under_prefix():
    """Row 1: a staged set whose every path is under the orchestration prefix → True."""
    assert orchestration_only_staged([
        "three-pillars-docs/tp-designs/orchestration/handoff.md",
        "three-pillars-docs/tp-designs/orchestration/campaign.md",
    ]) is True


def test_orchestration_only_staged_mixed_empty_none_false():
    """Row 2: mixed set (one outside path) → False; empty [] → False; None → False."""
    # mixed: one skills/foo.py among orchestration paths
    assert orchestration_only_staged([
        "three-pillars-docs/tp-designs/orchestration/handoff.md",
        "skills/foo.py",
    ]) is False
    # empty list
    assert orchestration_only_staged([]) is False
    # None
    assert orchestration_only_staged(None) is False


def test_orchestration_only_staged_backslash_normalized():
    """Row 3: a backslash-separated path under the prefix → False (strict match).

    orchestration_only_staged() is strict: backslash is a legal POSIX filename
    character, and a file literally named with backslash separators (OUTSIDE the
    orchestration slot) must NOT match the prefix. Backslash leniency lives only
    in the CLI --staged-file arm, not here.
    """
    assert orchestration_only_staged([
        "three-pillars-docs\\tp-designs\\orchestration\\handoff.md",
    ]) is False


# ---------------------------------------------------------------------------
# Task 1.2: assert_own_worktree staged_paths kwarg + Case-2 carve-out
# (design test-matrix rows 4-10)
# ---------------------------------------------------------------------------

# Reusable porcelain: master root + one healthy live tp/* worktree
_PORCELAIN_MASTER_ROOT_WITH_TP = """\
worktree /home/user/repo
HEAD abc123
branch refs/heads/master

worktree /home/user/repo-wt/a
HEAD def456
branch refs/heads/tp/a

"""

# Bare-root seat + one healthy live tp/* worktree
_PORCELAIN_BARE_ROOT_WITH_TP = """\
worktree /home/user/repo
HEAD abc123
bare

worktree /home/user/repo-wt/a
HEAD def456
branch refs/heads/tp/a

"""

# Drifted tp worktree (Case-3 scenario for row 9)
_PORCELAIN_DRIFTED_TP_A = """\
worktree /home/user/repo
HEAD abc123
branch refs/heads/master

worktree /home/user/repo-wt/a
HEAD def456
branch refs/heads/candidate/some-design/single

"""

_ORCHESTRATION_ONLY_STAGED = [
    "three-pillars-docs/tp-designs/orchestration/handoff.md",
]

_MIXED_STAGED = [
    "three-pillars-docs/tp-designs/orchestration/handoff.md",
    "skills/foo.py",
]

_CODE_STAGED = ["skills/worktree_isolation_guard.py"]


def test_assert_own_seat_orchestration_only_staged_passes():
    """Row 4: master-root cwd, tp/* live, staged = orchestration-only → PASS."""
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo",
        worktree_porcelain=_PORCELAIN_MASTER_ROOT_WITH_TP,
        current_branch="master",
        staged_paths=_ORCHESTRATION_ONLY_STAGED,
    )
    assert ok is True
    assert msg == ""


def test_assert_own_seat_mixed_staging_blocks_with_corruption_message():
    """Row 5: master-root cwd, tp/* live, staged = orchestration + one outside path
    → BLOCK; message contains 'shared-worktree corruption class' text (byte-identity).
    """
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo",
        worktree_porcelain=_PORCELAIN_MASTER_ROOT_WITH_TP,
        current_branch="master",
        staged_paths=_MIXED_STAGED,
    )
    assert ok is False
    assert "shared-worktree corruption class" in msg


def test_assert_own_seat_single_code_file_blocks():
    """Row 6: master-root cwd, tp/* live, staged = single code file → BLOCK."""
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo",
        worktree_porcelain=_PORCELAIN_MASTER_ROOT_WITH_TP,
        current_branch="master",
        staged_paths=_CODE_STAGED,
    )
    assert ok is False
    assert msg


def test_assert_own_seat_staged_none_blocks():
    """Row 7: master-root cwd, tp/* live, staged_paths=None → BLOCK (fail-closed;
    legacy-caller compatibility).
    """
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo",
        worktree_porcelain=_PORCELAIN_MASTER_ROOT_WITH_TP,
        current_branch="master",
        staged_paths=None,
    )
    assert ok is False
    assert msg


def test_assert_own_bare_root_orchestration_only_staged_passes():
    """Row 8: bare-root seat (porcelain 'bare', no branch line), tp/* live,
    orchestration-only staged → PASS (carve-out on the documented bare-base topology).
    """
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo",
        worktree_porcelain=_PORCELAIN_BARE_ROOT_WITH_TP,
        current_branch="",
        staged_paths=_ORCHESTRATION_ONLY_STAGED,
    )
    assert ok is True
    assert msg == ""


def test_assert_own_drifted_tp_orchestration_only_staged_blocks():
    """Row 9: Case-3 drift (cwd in -wt/<slug>, foreign HEAD), orchestration-only
    staged → BLOCK (carve-out is Case-2 only, not Case-3).
    """
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo-wt/a",
        worktree_porcelain=_PORCELAIN_DRIFTED_TP_A,
        current_branch="candidate/some-design/single",
        staged_paths=_ORCHESTRATION_ONLY_STAGED,
    )
    assert ok is False
    assert msg


def test_assert_own_worker_own_worktree_any_staged_passes():
    """Row 10: worker in own tp worktree, any staged set → PASS (non-Case-2 unaffected)."""
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo-wt/a",
        worktree_porcelain=_PORCELAIN_MASTER_ROOT_WITH_TP,
        current_branch="tp/a",
        staged_paths=_CODE_STAGED,
    )
    assert ok is True
    assert msg == ""


# ---------------------------------------------------------------------------
# Task 1.3: CLI staged-path resolution (design test-matrix rows 11-12)
# ---------------------------------------------------------------------------


def test_main_assert_own_staged_file_orchestration_passes():
    """Row 11: --assert-own-worktree --cwd <master-root> --worktree-porcelain <tp-live>
    --staged-file three-pillars-docs/tp-designs/orchestration/handoff.md → exit 0.
    """
    rc, stderr = _run_main([
        "--assert-own-worktree",
        "--cwd", "/home/user/repo",
        "--worktree-porcelain", _PORCELAIN_MASTER_ROOT_WITH_TP,
        "--branch", "master",
        "--staged-file", "three-pillars-docs/tp-designs/orchestration/handoff.md",
    ])
    assert rc == 0, f"orchestration-only staged on seat should exit 0; stderr={stderr!r}"
    assert not stderr


def test_main_assert_own_no_staged_and_mixed_block():
    """Row 12: --no-staged on a seat with live tp/* → exit 1;
    mixed --staged-file (orchestration + code path) → exit 1.
    """
    # --no-staged: hermetic empty set — carve-out can't fire → BLOCK
    rc_no_staged, stderr_no_staged = _run_main([
        "--assert-own-worktree",
        "--cwd", "/home/user/repo",
        "--worktree-porcelain", _PORCELAIN_MASTER_ROOT_WITH_TP,
        "--branch", "master",
        "--no-staged",
    ])
    assert rc_no_staged == 1, f"--no-staged on seat must block; stderr={stderr_no_staged!r}"
    assert stderr_no_staged

    # mixed --staged-file: orchestration + code path → BLOCK
    rc_mixed, stderr_mixed = _run_main([
        "--assert-own-worktree",
        "--cwd", "/home/user/repo",
        "--worktree-porcelain", _PORCELAIN_MASTER_ROOT_WITH_TP,
        "--branch", "master",
        "--staged-file", "three-pillars-docs/tp-designs/orchestration/handoff.md",
        "--staged-file", "skills/foo.py",
    ])
    assert rc_mixed == 1, f"mixed staged-file on seat must block; stderr={stderr_mixed!r}"
    assert stderr_mixed


# ---------------------------------------------------------------------------
# Adversarial boundary: orchestration_only_staged() directory-boundary pins
# ada #1 normpath fix + ada #2 behavioral pins
# ---------------------------------------------------------------------------


def test_orchestration_only_staged_sibling_dir_trap():
    """Sibling directory whose name starts with 'orchestration-' must NOT match.

    e.g. three-pillars-docs/tp-designs/orchestration-evil/x.md → False
    The prefix check is for 'orchestration/' (with trailing slash); a sibling
    like 'orchestration-evil/' must never be confused with the real carve-out slot.
    """
    assert orchestration_only_staged([
        "three-pillars-docs/tp-designs/orchestration-evil/x.md",
    ]) is False


def test_orchestration_only_staged_nested_prefix_trap():
    """A path that has the orchestration prefix as a non-root segment → False.

    e.g. a/three-pillars-docs/tp-designs/orchestration/x.md → False
    The carve-out only applies to paths rooted at the repo root; a leading
    directory segment must not cause a false positive.
    """
    assert orchestration_only_staged([
        "a/three-pillars-docs/tp-designs/orchestration/x.md",
    ]) is False


def test_orchestration_only_staged_bare_dir_without_trailing_slash():
    """Bare directory path without trailing slash → False (not a file under the slot).

    e.g. three-pillars-docs/tp-designs/orchestration → False
    The prefix includes a trailing slash so the bare directory name itself
    does not qualify.
    """
    assert orchestration_only_staged([
        "three-pillars-docs/tp-designs/orchestration",
    ]) is False


def test_orchestration_only_staged_dotdot_traversal_is_false():
    """A ..‑traversal path that resolves outside the orchestration slot → False.

    e.g. three-pillars-docs/tp-designs/orchestration/../../../skills/evil.py
    After normpath this is 'skills/evil.py', which does NOT start with the
    orchestration prefix — the carve-out must not fire.
    This pins the normpath fix introduced for audit finding ada #1.
    """
    assert orchestration_only_staged([
        "three-pillars-docs/tp-designs/orchestration/../../../skills/evil.py",
    ]) is False


# ---------------------------------------------------------------------------
# PR-fix-r1: production staged-source arm coverage
# Pins (a) default git-read arm, (b) --no-renames rename detection,
# (c) git-error → None → BLOCK, (d) drifted-seat-HEAD gate
# ---------------------------------------------------------------------------


def _make_git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with an initial commit for seam testing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "master"], cwd=repo, check=True,
                   capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo,
                   check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo,
                   check=True, capture_output=True)
    # Pin diff.renames=true so the rename-blocks test kills the drop-`--no-renames`
    # mutant regardless of runner gitconfig (some CIs default to false/0).
    subprocess.run(["git", "config", "diff.renames", "true"], cwd=repo,
                   check=True, capture_output=True)
    # Pin core.quotePath=true so the non-ASCII test kills the drop-`-z` mutant
    # regardless of runner gitconfig (quotePath=false emits raw names that a
    # newline-split parse would also accept).
    subprocess.run(["git", "config", "core.quotePath", "true"], cwd=repo,
                   check=True, capture_output=True)
    # Create and commit an initial file so HEAD exists
    (repo / "README.md").write_text("init")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True,
                   capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True,
                   capture_output=True)
    return repo


def test_cli_default_staged_arm_orchestration_only_passes(tmp_path):
    """(a) Default git-read arm: staged orchestration-only file + dirty-unstaged
    code file → carve-out PASS.

    The CLI reads the STAGED set (git diff --cached), not the working tree. A
    dirty code file that is NOT staged must NOT contribute to the staged set,
    so the carve-out fires correctly.
    """
    repo = _make_git_repo(tmp_path)

    # Set up: orchestration slot directory
    orch_dir = repo / "three-pillars-docs" / "tp-designs" / "orchestration"
    orch_dir.mkdir(parents=True)

    # Stage only the orchestration file
    handoff = orch_dir / "handoff.md"
    handoff.write_text("orchestration handoff")
    subprocess.run(["git", "add", str(handoff)], cwd=repo, check=True,
                   capture_output=True)

    # Dirty (unstaged) code file — must NOT appear in staged set
    code = repo / "skills" / "foo.py"
    code.parent.mkdir(parents=True, exist_ok=True)
    code.write_text("# dirty code")
    # Deliberately NOT staged

    # Build a porcelain that looks like the seat (master + tp/* live)
    porcelain_seat_tp = (
        f"worktree {repo}\n"
        "HEAD abc123\n"
        "branch refs/heads/master\n"
        "\n"
        f"worktree {tmp_path}/repo-wt/a\n"
        "HEAD def456\n"
        "branch refs/heads/tp/a\n"
        "\n"
    )
    rc, stderr = _run_main([
        "--assert-own-worktree",
        "--repo", str(repo),
        "--cwd", str(repo),
        "--worktree-porcelain", porcelain_seat_tp,
        "--branch", "master",
        # No --staged-file / --no-staged: CLI reads from git (the default arm)
    ])
    assert rc == 0, (
        f"staged orchestration-only file + dirty-unstaged code → should PASS "
        f"(carve-out); stderr={stderr!r}"
    )
    assert not stderr


def test_cli_default_staged_arm_code_staged_blocks(tmp_path):
    """(a) Default git-read arm: staged code file + dirty-unstaged orchestration
    file → BLOCK.

    The staged set contains a code file, so the carve-out must not fire even
    though an orchestration file exists in the working tree (unstaged).
    """
    repo = _make_git_repo(tmp_path)

    # Stage only a code file
    code = repo / "skills" / "foo.py"
    code.parent.mkdir(parents=True, exist_ok=True)
    code.write_text("# staged code")
    subprocess.run(["git", "add", str(code)], cwd=repo, check=True,
                   capture_output=True)

    # Dirty (unstaged) orchestration file — must NOT satisfy the carve-out
    orch_dir = repo / "three-pillars-docs" / "tp-designs" / "orchestration"
    orch_dir.mkdir(parents=True)
    (orch_dir / "handoff.md").write_text("dirty")
    # Deliberately NOT staged

    porcelain_seat_tp = (
        f"worktree {repo}\n"
        "HEAD abc123\n"
        "branch refs/heads/master\n"
        "\n"
        f"worktree {tmp_path}/repo-wt/a\n"
        "HEAD def456\n"
        "branch refs/heads/tp/a\n"
        "\n"
    )
    rc, stderr = _run_main([
        "--assert-own-worktree",
        "--repo", str(repo),
        "--cwd", str(repo),
        "--worktree-porcelain", porcelain_seat_tp,
        "--branch", "master",
    ])
    assert rc == 1, (
        f"staged code file + dirty-unstaged orchestration → should BLOCK; "
        f"stderr={stderr!r}"
    )
    assert stderr


def test_cli_default_staged_arm_rename_from_outside_blocks(tmp_path):
    """(b) --no-renames pin: a staged rename whose SOURCE is outside the
    orchestration slot produces BLOCK.

    With --no-renames both rename sides appear in the output; without it only
    the destination would appear (rename detection), which could smuggle a
    non-orchestration file past the carve-out. The staged-source resolution
    must use --no-renames so mixed-staging detection fires.
    """
    repo = _make_git_repo(tmp_path)

    # Create a code file and commit it (so git can detect a rename from it)
    code = repo / "skills" / "important.py"
    code.parent.mkdir(parents=True, exist_ok=True)
    code.write_text("# code file to be renamed")
    subprocess.run(["git", "add", str(code)], cwd=repo, check=True,
                   capture_output=True)
    subprocess.run(["git", "commit", "-m", "add code file"], cwd=repo,
                   check=True, capture_output=True)

    # Stage a rename: skills/important.py → three-pillars-docs/tp-designs/orchestration/renamed.py
    orch_dir = repo / "three-pillars-docs" / "tp-designs" / "orchestration"
    orch_dir.mkdir(parents=True)
    dest = orch_dir / "renamed.py"
    subprocess.run(["git", "mv", str(code), str(dest)], cwd=repo, check=True,
                   capture_output=True)
    # At this point the rename is staged: source (skills/important.py) was outside
    # the allowlist, destination is inside. With --no-renames both sides appear.

    porcelain_seat_tp = (
        f"worktree {repo}\n"
        "HEAD abc123\n"
        "branch refs/heads/master\n"
        "\n"
        f"worktree {tmp_path}/repo-wt/a\n"
        "HEAD def456\n"
        "branch refs/heads/tp/a\n"
        "\n"
    )
    rc, stderr = _run_main([
        "--assert-own-worktree",
        "--repo", str(repo),
        "--cwd", str(repo),
        "--worktree-porcelain", porcelain_seat_tp,
        "--branch", "master",
    ])
    assert rc == 1, (
        f"staged rename from outside-allowlist source → must BLOCK (--no-renames "
        f"exposes both sides); stderr={stderr!r}"
    )
    assert stderr


def test_cli_git_error_staged_arm_blocks(tmp_path):
    """(c) git-error → staged_paths=None → BLOCK (fail-closed).

    When the git diff --cached invocation fails (e.g. not a git repo, git
    unavailable), staged_paths is set to None — the carve-out can't fire and
    the guard must BLOCK fail-closed.
    """
    # A non-repo directory — git will fail with a fatal error
    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()

    porcelain_seat_tp = (
        f"worktree {not_a_repo}\n"
        "HEAD abc123\n"
        "branch refs/heads/master\n"
        "\n"
        f"worktree {tmp_path}/repo-wt/a\n"
        "HEAD def456\n"
        "branch refs/heads/tp/a\n"
        "\n"
    )
    rc, stderr = _run_main([
        "--assert-own-worktree",
        "--repo", str(not_a_repo),
        "--cwd", str(not_a_repo),
        "--worktree-porcelain", porcelain_seat_tp,
        "--branch", "master",
    ])
    assert rc == 1, (
        f"git-error in staged-source arm → staged_paths=None → must BLOCK "
        f"(fail-closed); stderr={stderr!r}"
    )
    assert stderr


def test_assert_own_drifted_seat_head_orchestration_staged_blocks():
    """(d) Drifted-seat-HEAD gate: when the seat's HEAD is on a named non-default
    branch (e.g. tp/b), an orchestration-only staged commit must BLOCK.

    _is_default_branch_root() classifies the main-checkout path shape as the
    seat via the path-shape fallback even when its branch is a non-default named
    branch (e.g. tp/b). Without the drifted-seat-HEAD gate, orchestration-only
    staging would PASS — landing the paper-trail commit on tp/b where it is lost
    to the orchestration slot.

    The gate requires effective_branch to be empty or in _DEFAULT_BRANCHES
    before consulting the carve-out; a drifted named branch must BLOCK.
    """
    # Porcelain: master checkout has drifted to tp/b in-place; tp/a is live
    porcelain_drifted_seat = """\
worktree /home/user/repo
HEAD abc123
branch refs/heads/tp/b

worktree /home/user/repo-wt/a
HEAD def456
branch refs/heads/tp/a

"""
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo",
        worktree_porcelain=porcelain_drifted_seat,
        current_branch="tp/b",
        staged_paths=[
            "three-pillars-docs/tp-designs/orchestration/handoff.md",
        ],
    )
    assert ok is False, (
        "drifted seat (HEAD on tp/b) + orchestration-only staged → must BLOCK "
        "(carve-out must not fire on a non-default-branch seat)"
    )
    assert msg


def test_assert_own_drifted_seat_feature_branch_blocks():
    """(d) Drifted-seat-HEAD gate: feature/* branch on seat → BLOCK even with
    orchestration-only staging.

    Complements the tp/b case: any non-default named branch on the seat
    (including feature/*) must take the BLOCK path.
    """
    porcelain_feature_seat = """\
worktree /home/user/repo
HEAD abc123
branch refs/heads/feature/x

worktree /home/user/repo-wt/a
HEAD def456
branch refs/heads/tp/a

"""
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo",
        worktree_porcelain=porcelain_feature_seat,
        current_branch="feature/x",
        staged_paths=[
            "three-pillars-docs/tp-designs/orchestration/handoff.md",
        ],
    )
    assert ok is False, (
        "drifted seat (HEAD on feature/x) + orchestration-only staged → must BLOCK"
    )
    assert msg


def test_assert_own_bare_seat_orchestration_staged_passes_gate():
    """(d) Drifted-seat-HEAD gate: bare/branchless seat (effective_branch="")
    still PASSes the gate — the carve-out must fire for the legitimate bare topology.

    effective_branch="" is the bare-base-checkout case; it must not be conflated
    with a drifted named branch.
    """
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo",
        worktree_porcelain=_PORCELAIN_BARE_ROOT_WITH_TP,
        current_branch="",
        staged_paths=[
            "three-pillars-docs/tp-designs/orchestration/handoff.md",
        ],
    )
    assert ok is True, (
        "bare seat (effective_branch='') + orchestration-only staged → must PASS "
        "(bare topology is a legitimate default-branch root)"
    )
    assert msg == ""


# ---------------------------------------------------------------------------
# PR-fix-r2: backslash-named-file smuggling + bare-vs-detached gate +
# -z non-ASCII pin
# ---------------------------------------------------------------------------


def test_main_staged_file_backslash_cli_arm_passes():
    """CLI --staged-file arm: Windows-style backslash separators → PASS.

    The CLI --staged-file arm normalizes backslashes before calling
    orchestration_only_staged(), so a human typing Windows-style separators
    is treated leniently. This is the ONLY place the leniency lives.
    """
    rc, stderr = _run_main([
        "--assert-own-worktree",
        "--cwd", "/home/user/repo",
        "--worktree-porcelain", _PORCELAIN_MASTER_ROOT_WITH_TP,
        "--branch", "master",
        "--staged-file",
        "three-pillars-docs\\tp-designs\\orchestration\\handoff.md",
    ])
    assert rc == 0, (
        f"--staged-file with backslash separators must PASS (CLI leniency arm); "
        f"stderr={stderr!r}"
    )
    assert not stderr


def test_cli_default_arm_backslash_filename_blocks(tmp_path):
    """Default arm (live git read): a file whose POSIX name literally contains
    backslashes (outside the orchestration slot) must BLOCK — the backslash
    normalisation must NOT smuggle it past the prefix check.

    This pins the structural fix: orchestration_only_staged() is strict;
    backslash leniency is only in the --staged-file CLI arm.
    """
    import os as _os
    repo = _make_git_repo(tmp_path)

    # Create and stage a file whose name literally contains backslashes.
    # The name looks like a nested path under the orchestration prefix when
    # backslashes are naively normalised, but POSIX treats the whole thing as
    # a single flat filename in the repo root — it is OUTSIDE the slot.
    evil_name = "three-pillars-docs\\tp-designs\\orchestration\\evil.md"
    evil_file = repo / evil_name
    evil_file.write_text("smuggled content")
    subprocess.run(["git", "add", "--", evil_name], cwd=repo,
                   check=True, capture_output=True)

    porcelain_seat_tp = (
        f"worktree {repo}\n"
        "HEAD abc123\n"
        "branch refs/heads/master\n"
        "\n"
        f"worktree {tmp_path}/repo-wt/a\n"
        "HEAD def456\n"
        "branch refs/heads/tp/a\n"
        "\n"
    )
    rc, stderr = _run_main([
        "--assert-own-worktree",
        "--repo", str(repo),
        "--cwd", str(repo),
        "--worktree-porcelain", porcelain_seat_tp,
        "--branch", "master",
        # No --staged-file / --no-staged: CLI reads from git (the default arm)
    ])
    assert rc == 1, (
        f"backslash-named file outside slot must BLOCK (no smuggling); "
        f"stderr={stderr!r}"
    )
    assert stderr


def test_assert_own_detached_non_bare_seat_orchestration_staged_blocks():
    """BLOCK: detached non-bare seat (porcelain 'detached', empty branch) with
    orchestration-only staged must NOT get the carve-out.

    A detached HEAD is not a known-safe branchless topology (it is not the
    bare-base-checkout seat). The seat_on_default gate now requires
    owner_is_bare for the empty-branch arm; a non-bare detached seat must BLOCK.
    """
    # Porcelain: a non-bare worktree with a detached HEAD (no branch line) +
    # a live tp/* worktree.
    porcelain_detached_seat = """\
worktree /home/user/repo
HEAD abc123
detached

worktree /home/user/repo-wt/a
HEAD def456
branch refs/heads/tp/a

"""
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo",
        worktree_porcelain=porcelain_detached_seat,
        current_branch="",   # detached HEAD → porcelain has no branch → ""
        staged_paths=[
            "three-pillars-docs/tp-designs/orchestration/handoff.md",
        ],
    )
    assert ok is False, (
        "detached non-bare seat + orchestration-only staged → must BLOCK "
        "(carve-out must not fire on a non-bare branchless seat)"
    )
    assert msg


def test_cli_default_arm_non_ascii_orchestration_passes(tmp_path):
    """Non-ASCII filename pin for the -z arm: stage an orchestration file with
    a non-ASCII name (e.g. händoff.md) and assert the carve-out PASSes.

    This pins the -z flag: git diff --cached --name-only -z emits raw NUL-
    separated unquoted bytes, so non-ASCII filenames are transmitted verbatim
    without C-escaping. A drop-`-z` mutant would C-escape the name and the
    NUL-split would fail or produce garbage, causing a BLOCK instead of PASS.
    """
    repo = _make_git_repo(tmp_path)

    orch_dir = repo / "three-pillars-docs" / "tp-designs" / "orchestration"
    orch_dir.mkdir(parents=True)

    # Non-ASCII filename in the orchestration slot
    handoff = orch_dir / "händoff.md"
    handoff.write_text("non-ascii orchestration handoff", encoding="utf-8")
    subprocess.run(["git", "add", str(handoff)], cwd=repo, check=True,
                   capture_output=True)

    porcelain_seat_tp = (
        f"worktree {repo}\n"
        "HEAD abc123\n"
        "branch refs/heads/master\n"
        "\n"
        f"worktree {tmp_path}/repo-wt/a\n"
        "HEAD def456\n"
        "branch refs/heads/tp/a\n"
        "\n"
    )
    rc, stderr = _run_main([
        "--assert-own-worktree",
        "--repo", str(repo),
        "--cwd", str(repo),
        "--worktree-porcelain", porcelain_seat_tp,
        "--branch", "master",
    ])
    assert rc == 0, (
        f"non-ASCII orchestration filename + -z arm → must PASS (carve-out); "
        f"stderr={stderr!r}"
    )
