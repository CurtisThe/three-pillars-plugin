"""Tests for worktree_write_guard.py — the leak predicate.

Tests drive the predicate via override flags (--branch, --staged-file,
--worktree-porcelain) so no real git state is needed.

Run with: python -m pytest skills/_shared/test_worktree_write_guard.py -q

Design refs:
  - three-pillars-docs/completed-tp-designs/worktree-write-guard/detailed-design.md
  - three-pillars-docs/completed-tp-designs/worktree-write-guard/plan.md
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr

import pytest

import worktree_write_guard
from worktree_write_guard import (
    live_tp_worktrees,
    is_guarded_path,
    should_block,
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


def _run_main(args):
    """Call main(argv) and return (return_code, stderr_output)."""
    buf = io.StringIO()
    with redirect_stderr(buf):
        rc = main(args)
    return rc, buf.getvalue()


# ---------------------------------------------------------------------------
# Task 1.1: live_tp_worktrees
# ---------------------------------------------------------------------------


def test_live_tp_worktrees_mixed():
    result = live_tp_worktrees(_PORCELAIN_MASTER_AND_TP)
    assert result == ["tp/a", "tp/b"]


def test_live_tp_worktrees_master_only():
    result = live_tp_worktrees(_PORCELAIN_MASTER_ONLY)
    assert result == []


def test_live_tp_worktrees_single_tp():
    result = live_tp_worktrees(_PORCELAIN_WITH_TP_X)
    assert result == ["tp/x"]


# ---------------------------------------------------------------------------
# Task 1.2: is_guarded_path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,expected",
    [
        # TRUE (guarded) — framework code
        ("skills/tp-plan/SKILL.md", True),
        ("framework-check.sh", True),
        ("skills/_shared/x.py", True),
        # TRUE (guarded) — design artifacts under tp-designs/<slug>/
        ("three-pillars-docs/tp-designs/foo/plan.md", True),
        ("three-pillars-docs/tp-designs/foo/lock.json", True),
        ("three-pillars-docs/tp-designs/foo/design.md", True),
        ("three-pillars-docs/tp-designs/foo/detailed-design.md", True),
        ("three-pillars-docs/tp-designs/foo/decisions.md", True),
        ("three-pillars-docs/tp-designs/foo/review.md", True),
        ("three-pillars-docs/tp-designs/foo/implementation-audit.md", True),
        ("three-pillars-docs/tp-designs/foo/spike-results.md", True),
        # FALSE — seeds are NOT in DESIGN_ARTIFACTS
        ("three-pillars-docs/tp-designs/foo/seed.md", False),
        # FALSE — living docs
        ("three-pillars-docs/known_issues.md", False),
        ("three-pillars-docs/vision.md", False),
        ("three-pillars-docs/architecture.md", False),
        ("three-pillars-docs/product_roadmap.md", False),
        ("three-pillars-docs/RELEASING.md", False),
        # FALSE — release files (load-bearing regression pin)
        (".claude-plugin/marketplace.json", False),
        (".claude-plugin/plugin.json", False),
        # FALSE — archived designs
        ("completed-tp-designs/foo/plan.md", False),
        ("three-pillars-docs/completed-tp-designs/foo/plan.md", False),
        # FALSE — root docs
        ("README.md", False),
        ("CLAUDE.md", False),
    ],
)
def test_is_guarded_path(path, expected):
    assert is_guarded_path(path) == expected, (
        f"is_guarded_path({path!r}) expected {expected}"
    )


# ---------------------------------------------------------------------------
# Task 1.3: should_block truth table
# ---------------------------------------------------------------------------


def test_should_block_leak_case():
    """The 1 blocking case: default branch + tp live + guarded staged path."""
    blocked, msg = should_block(
        branch="master",
        staged_paths=["skills/foo.py"],
        worktree_porcelain=_PORCELAIN_WITH_TP_X,
    )
    assert blocked is True
    assert msg  # guidance message must be non-empty


def test_should_block_guidance_content():
    """Guidance message must name the branch, the live worktree, and the cd fix."""
    blocked, msg = should_block(
        branch="master",
        staged_paths=["skills/foo.py"],
        worktree_porcelain=_PORCELAIN_WITH_TP_X,
    )
    assert "master" in msg
    assert "tp/x" in msg
    assert "cd" in msg


@pytest.mark.parametrize(
    "desc,branch,staged_paths,porcelain",
    [
        # (a) non-default branch + guarded path
        (
            "non-default branch with guarded path",
            "tp/x",
            ["skills/foo.py"],
            _PORCELAIN_WITH_TP_X,
        ),
        # (b) default branch, no tp worktree live
        (
            "default branch, no tp worktree",
            "master",
            ["skills/foo.py"],
            _PORCELAIN_MASTER_ONLY,
        ),
        # (c) default + tp live + seed-only staged
        (
            "seed-only staged",
            "master",
            ["three-pillars-docs/tp-designs/x/seed.md"],
            _PORCELAIN_WITH_TP_X,
        ),
        # (d) default + tp live + living-doc-only staged
        (
            "living-doc-only staged",
            "master",
            ["three-pillars-docs/known_issues.md"],
            _PORCELAIN_WITH_TP_X,
        ),
        # (e) default + tp live + release-file-only staged
        (
            "release-file-only staged",
            "master",
            [".claude-plugin/marketplace.json"],
            _PORCELAIN_WITH_TP_X,
        ),
        # (f) default + tp live + empty staged list
        (
            "empty staged list",
            "master",
            [],
            _PORCELAIN_WITH_TP_X,
        ),
        # (g) guarded path but branch is tp/*
        (
            "guarded path on tp/* branch",
            "tp/x",
            ["three-pillars-docs/tp-designs/x/plan.md"],
            _PORCELAIN_WITH_TP_X,
        ),
    ],
)
def test_should_block_non_blocking(desc, branch, staged_paths, porcelain):
    blocked, msg = should_block(
        branch=branch,
        staged_paths=staged_paths,
        worktree_porcelain=porcelain,
    )
    assert blocked is False, f"Expected not blocked for: {desc}"
    assert msg == "", f"Expected empty message for: {desc}"


# ---------------------------------------------------------------------------
# Task 1.4: main CLI with override flags
# ---------------------------------------------------------------------------


def test_main_leak_case_exits_1():
    """Leak case: exit 1 + guidance on stderr."""
    rc, stderr = _run_main([
        "--branch", "master",
        "--worktree-porcelain", _PORCELAIN_WITH_TP_X,
        "--staged-file", "skills/foo.py",
    ])
    assert rc == 1
    assert stderr  # guidance must be on stderr


def test_main_seed_only_exits_0():
    """Seed-only staged: exit 0."""
    rc, stderr = _run_main([
        "--branch", "master",
        "--worktree-porcelain", _PORCELAIN_WITH_TP_X,
        "--staged-file", "three-pillars-docs/tp-designs/x/seed.md",
    ])
    assert rc == 0
    assert not stderr


def test_main_no_worktree_exits_0():
    """No tp worktree live: exit 0."""
    rc, stderr = _run_main([
        "--branch", "master",
        "--worktree-porcelain", _PORCELAIN_MASTER_ONLY,
        "--staged-file", "skills/foo.py",
    ])
    assert rc == 0
    assert not stderr


def test_main_empty_staged_exits_0():
    """Empty staged set (explicit --no-staged): exit 0 even with live tp/* worktrees.

    This is the load-bearing no-commit / CI case: framework-check runs with
    nothing staged and must never self-block. Expressed hermetically via
    --no-staged so the assertion does not depend on the ambient git index
    (the pass-by-luck leak this design closes).
    """
    rc, stderr = _run_main([
        "--branch", "master",
        "--worktree-porcelain", _PORCELAIN_WITH_TP_X,
        "--no-staged",  # explicit empty staged override — never reads the real index
    ])
    assert rc == 0
    assert not stderr


def test_main_no_staged_and_staged_file_mutually_exclusive():
    """--no-staged and --staged-file are contradictory ⇒ argparse exits 2."""
    with pytest.raises(SystemExit):
        main([
            "--branch", "master",
            "--worktree-porcelain", _PORCELAIN_WITH_TP_X,
            "--no-staged",
            "--staged-file", "skills/foo.py",
        ])
