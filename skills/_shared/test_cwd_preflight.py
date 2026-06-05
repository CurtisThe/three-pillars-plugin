"""Tests for cwd_preflight.py — the fail-open cwd preflight helper.

Tests drive check_cwd and main via override flags so no real git state needed.
The preflight is fail-open: any git error → exit 0 (never false-blocks).

Run with: python -m pytest skills/_shared/test_cwd_preflight.py -q

Design refs:
  - three-pillars-docs/completed-tp-designs/worktree-write-guard/detailed-design.md
  - three-pillars-docs/completed-tp-designs/worktree-write-guard/plan.md
"""

from __future__ import annotations

import io
import os
from contextlib import redirect_stderr

import pytest

import cwd_preflight
from cwd_preflight import (
    target_worktree_path,
    check_cwd,
    main,
)


# ---------------------------------------------------------------------------
# Porcelain fixture helpers
# ---------------------------------------------------------------------------

def _make_porcelain(worktrees: list[tuple[str, str]]) -> str:
    """Build a porcelain string from (path, branch_ref) pairs."""
    lines = []
    for path, branch_ref in worktrees:
        lines.append(f"worktree {path}")
        lines.append("HEAD abc123")
        lines.append(f"branch {branch_ref}")
        lines.append("")
    return "\n".join(lines) + "\n"


_PORCELAIN_WITH_FOO = _make_porcelain([
    ("/home/user/repo", "refs/heads/master"),
    ("/home/user/repo-wt/foo", "refs/heads/tp/foo"),
])

_PORCELAIN_NO_FOO = _make_porcelain([
    ("/home/user/repo", "refs/heads/master"),
])

_PORCELAIN_DIFF_DESIGN = _make_porcelain([
    ("/home/user/repo", "refs/heads/master"),
    ("/home/user/repo-wt/bar", "refs/heads/tp/bar"),
])


def _run_main(args):
    """Call main(argv) and return (return_code, stderr_output)."""
    buf = io.StringIO()
    with redirect_stderr(buf):
        rc = main(args)
    return rc, buf.getvalue()


# ---------------------------------------------------------------------------
# Task 3.1: target_worktree_path
# ---------------------------------------------------------------------------


def test_target_worktree_path_found():
    """Returns the worktree path when a tp/<design> worktree exists."""
    result = target_worktree_path("/repo", "foo", worktree_porcelain=_PORCELAIN_WITH_FOO)
    assert result == "/home/user/repo-wt/foo"


def test_target_worktree_path_not_found():
    """Returns None when no tp/<design> worktree is present."""
    result = target_worktree_path("/repo", "foo", worktree_porcelain=_PORCELAIN_NO_FOO)
    assert result is None


def test_target_worktree_path_different_design():
    """Returns None when only a different tp/* worktree exists."""
    result = target_worktree_path("/repo", "foo", worktree_porcelain=_PORCELAIN_DIFF_DESIGN)
    assert result is None


def test_target_worktree_path_matches_exact_design():
    """Matches exactly tp/<design>, not a prefix of another design."""
    porcelain = _make_porcelain([
        ("/home/user/repo", "refs/heads/master"),
        ("/home/user/repo-wt/foobar", "refs/heads/tp/foobar"),
    ])
    result = target_worktree_path("/repo", "foo", worktree_porcelain=porcelain)
    assert result is None


# ---------------------------------------------------------------------------
# Task 3.2: check_cwd
# ---------------------------------------------------------------------------


def test_check_cwd_refuse_when_outside_worktree(tmp_path):
    """Refuse when tp/<design> worktree exists and cwd is not inside it."""
    target = str(tmp_path / "repo-wt" / "foo")
    porcelain = _make_porcelain([
        (str(tmp_path / "repo"), "refs/heads/master"),
        (target, "refs/heads/tp/foo"),
    ])
    cwd = str(tmp_path / "repo")
    ok, msg = check_cwd(
        cwd=cwd,
        design="foo",
        repo_root=str(tmp_path / "repo"),
        worktree_porcelain=porcelain,
    )
    assert ok is False
    assert msg  # message must be non-empty
    assert target in msg  # must name the worktree path
    assert "cd" in msg  # must include cd fix


def test_check_cwd_ok_when_inside_worktree(tmp_path):
    """Ok when cwd is inside the target worktree."""
    target = str(tmp_path / "repo-wt" / "foo")
    porcelain = _make_porcelain([
        (str(tmp_path / "repo"), "refs/heads/master"),
        (target, "refs/heads/tp/foo"),
    ])
    # cwd == target (inside the worktree)
    ok, msg = check_cwd(
        cwd=target,
        design="foo",
        repo_root=str(tmp_path / "repo"),
        worktree_porcelain=porcelain,
    )
    assert ok is True
    assert msg == ""


def test_check_cwd_ok_when_cwd_subdir_of_worktree(tmp_path):
    """Ok when cwd is a subdirectory of the target worktree."""
    target = str(tmp_path / "repo-wt" / "foo")
    subdir = str(tmp_path / "repo-wt" / "foo" / "skills")
    porcelain = _make_porcelain([
        (str(tmp_path / "repo"), "refs/heads/master"),
        (target, "refs/heads/tp/foo"),
    ])
    ok, msg = check_cwd(
        cwd=subdir,
        design="foo",
        repo_root=str(tmp_path / "repo"),
        worktree_porcelain=porcelain,
    )
    assert ok is True
    assert msg == ""


def test_check_cwd_ok_when_no_worktree(tmp_path):
    """Ok (normal single-checkout) when no tp/<design> worktree exists."""
    porcelain = _make_porcelain([
        (str(tmp_path / "repo"), "refs/heads/master"),
    ])
    ok, msg = check_cwd(
        cwd=str(tmp_path / "repo"),
        design="foo",
        repo_root=str(tmp_path / "repo"),
        worktree_porcelain=porcelain,
    )
    assert ok is True
    assert msg == ""


def test_check_cwd_refuse_message_includes_cd_fix(tmp_path):
    """Refuse message includes the cd fix pointing to the worktree path."""
    target = str(tmp_path / "repo-wt" / "foo")
    porcelain = _make_porcelain([
        (str(tmp_path / "repo"), "refs/heads/master"),
        (target, "refs/heads/tp/foo"),
    ])
    ok, msg = check_cwd(
        cwd=str(tmp_path / "repo"),
        design="foo",
        repo_root=str(tmp_path / "repo"),
        worktree_porcelain=porcelain,
    )
    assert ok is False
    # Message should name the target path and suggest cd
    assert target in msg
    assert "cd" in msg


# ---------------------------------------------------------------------------
# Task 3.3: main CLI — exit 0/3 + fail-open on git error
# ---------------------------------------------------------------------------


def test_main_refuse_exits_3(tmp_path):
    """Refuse case: exit 3 + message printed."""
    target = str(tmp_path / "repo-wt" / "foo")
    porcelain = _make_porcelain([
        (str(tmp_path / "repo"), "refs/heads/master"),
        (target, "refs/heads/tp/foo"),
    ])
    rc, stderr = _run_main([
        "foo",
        "--cwd", str(tmp_path / "repo"),
        "--repo", str(tmp_path / "repo"),
        "--worktree-porcelain", porcelain,
    ])
    assert rc == 3
    assert stderr  # message on stderr


def test_main_ok_exits_0_inside_worktree(tmp_path):
    """Ok case (cwd inside worktree): exit 0."""
    target = str(tmp_path / "repo-wt" / "foo")
    porcelain = _make_porcelain([
        (str(tmp_path / "repo"), "refs/heads/master"),
        (target, "refs/heads/tp/foo"),
    ])
    rc, stderr = _run_main([
        "foo",
        "--cwd", target,
        "--repo", str(tmp_path / "repo"),
        "--worktree-porcelain", porcelain,
    ])
    assert rc == 0
    assert not stderr


def test_main_ok_exits_0_no_worktree(tmp_path):
    """Ok case (no tp/<design> worktree): exit 0."""
    porcelain = _make_porcelain([
        (str(tmp_path / "repo"), "refs/heads/master"),
    ])
    rc, stderr = _run_main([
        "foo",
        "--cwd", str(tmp_path / "repo"),
        "--repo", str(tmp_path / "repo"),
        "--worktree-porcelain", porcelain,
    ])
    assert rc == 0
    assert not stderr


def test_main_fail_open_on_git_error(tmp_path):
    """Fail-open: simulated git error → exit 0 (never false-blocks).

    Simulated by providing a --repo that doesn't exist (git will fail),
    but NOT providing --worktree-porcelain, so main will attempt a real git call.
    The fail-open contract means this must return 0 instead of crashing.
    """
    rc, stderr = _run_main([
        "foo",
        "--cwd", str(tmp_path / "repo"),
        "--repo", str(tmp_path / "nonexistent-repo"),
        # no --worktree-porcelain → will try real git and fail
    ])
    assert rc == 0  # fail-open: git error → never block
