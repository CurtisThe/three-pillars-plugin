"""Tests for worktree_isolation_guard.py — the worker isolation predicate.

Tests drive the predicate via override flags (--cwd, --worktree-porcelain,
--dispatch-sha, --return-sha) so no real git state is needed.

Run with: python -m pytest skills/_shared/test_worktree_isolation_guard.py -q

Design refs:
  - three-pillars-docs/tp-designs/fleet-worktree-isolation-guards/detailed-design.md
  - three-pillars-docs/tp-designs/fleet-worktree-isolation-guards/plan.md
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr
from pathlib import Path

import pytest

import worktree_isolation_guard
from worktree_isolation_guard import (
    live_tp_worktrees,
    is_shared_with_orchestrator,
    assert_own_worktree,
    forbid_checkout_in_shared,
    head_drift,
    main,
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
    content = fcs_path.read_text()

    # (1) Footer bumped to 33 (orchestration-master-seat added #33)
    assert "framework-check: all 33 invariants passed" in content, (
        "footer must read 'all 33 invariants passed'"
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
