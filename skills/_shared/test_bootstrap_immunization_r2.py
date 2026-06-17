"""Tests for bootstrap_immunization.py — round-2 review fixes.

Covers:
  - apply() pre-check heals core.bare=true bleed before enabling worktreeConfig
  - status CLI catches corrupt-config RuntimeError → {"error": ...} JSON exit 0

Run with: python -m pytest skills/_shared/test_bootstrap_immunization_r2.py -q
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
import sys
import os

import pytest

HERE = Path(__file__).parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "T",
    "GIT_AUTHOR_EMAIL": "t@test.com",
    "GIT_COMMITTER_NAME": "T",
    "GIT_COMMITTER_EMAIL": "t@test.com",
    "HOME": os.environ.get("HOME", os.path.expanduser("~")),
    "PATH": os.environ.get("PATH", ""),
}


def _git(cwd: Path, *args, check=True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
        env=_GIT_ENV,
    )


@pytest.fixture()
def linked_worktree_with_bleed(tmp_path):
    """Create main repo + linked worktree with core.bare=true bleed injected.

    Returns (main_repo, worktree_path).
    """
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-b", "master")
    _git(main, "config", "user.email", "t@test.com")
    _git(main, "config", "user.name", "T")
    _git(main, "config", "commit.gpgsign", "false")
    (main / "README").write_text("hello\n")
    _git(main, "add", "README")
    _git(main, "commit", "-m", "init")

    # Create a linked worktree (its .git is a file, not a directory)
    wt = tmp_path / "wt"
    _git(main, "worktree", "add", str(wt), "-b", "tp/linked")

    # Inject the bleed state: set core.bare=true in the shared config
    _git(main, "config", "--local", "core.bare", "true")

    return main, wt


# ---------------------------------------------------------------------------
# apply() pre-check: core.bare bleed healed before enabling worktreeConfig
# ---------------------------------------------------------------------------


def test_apply_heals_core_bare_bleed_before_worktree_config(
    linked_worktree_with_bleed,
):
    """apply() from a linked worktree with core.bare=true bleed heals it first.

    The bleed state (core.bare=true + .git is a file) is healed to
    core.bare=false BEFORE extensions.worktreeConfig is enabled.

    Mutation-verify: removing the pre-check causes apply() to enable
    worktreeConfig while core.bare=true, which would break all worktrees.
    This test verifies core.bare is false after apply().
    """
    from bootstrap_immunization import apply

    main_repo, worktree = linked_worktree_with_bleed

    # Verify bleed state is in place
    bare_before = subprocess.run(
        ["git", "config", "--local", "core.bare"],
        cwd=main_repo, capture_output=True, text=True, env=_GIT_ENV,
    ).stdout.strip()
    assert bare_before == "true", f"Expected bleed state (core.bare=true); got {bare_before!r}"

    # Apply from the linked worktree — should heal core.bare first
    apply(worktree)

    # core.bare must now be false (healed)
    bare_after = subprocess.run(
        ["git", "config", "--local", "core.bare"],
        cwd=main_repo, capture_output=True, text=True, env=_GIT_ENV,
    ).stdout.strip()
    assert bare_after == "false", (
        f"apply() must heal core.bare=true bleed; core.bare is still {bare_after!r}"
    )

    # extensions.worktreeConfig must also be set
    wc = subprocess.run(
        ["git", "config", "--local", "extensions.worktreeConfig"],
        cwd=main_repo, capture_output=True, text=True, env=_GIT_ENV,
    ).stdout.strip()
    assert wc.lower() == "true", (
        f"apply() must set extensions.worktreeConfig=true; got {wc!r}"
    )


def test_apply_heals_when_git_is_dir_and_core_bare_true(tmp_path):
    """apply() heals core.bare=true even when .git is a directory (seat bleed case).

    Under the corrected semantics, the heal gate is:
      core.bare=true AND (repo/.git) exists (file OR dir).
    The seat itself typically has .git as a directory, so seat-sourced apply()
    must also heal the bleed — this is the scenario the consenting surfaces
    (first-run offer, seat --apply) exercise most often.

    Mutation-verify: removing the heal gate in apply() means core.bare stays
    true after apply(), causing this test to fail.
    """
    from bootstrap_immunization import apply

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "master")
    _git(repo, "config", "user.email", "t@test.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "README").write_text("hello\n")
    _git(repo, "add", "README")
    _git(repo, "commit", "-m", "init")

    # Verify .git is a directory (seat layout)
    assert (repo / ".git").is_dir(), ".git must be a directory in a normal repo"

    # Inject bleed state: core.bare=true
    _git(repo, "config", "--local", "core.bare", "true")

    # apply() must heal core.bare=false before enabling worktreeConfig
    apply(repo)

    # core.bare must now be false (healed)
    bare_after = subprocess.run(
        ["git", "config", "--local", "core.bare"],
        cwd=repo, capture_output=True, text=True, env=_GIT_ENV,
    ).stdout.strip()
    assert bare_after == "false", (
        f"apply() must heal core.bare=true even when .git is a dir; "
        f"core.bare is still {bare_after!r}"
    )


def test_apply_no_heal_when_core_bare_absent(tmp_path):
    """apply() does NOT heal when core.bare is absent/false (healthy repo).

    The no-heal case is core.bare absent or false — not the .git-is-dir distinction.
    A healthy normal repo (core.bare unset or false) must go through apply()
    without any heal message being emitted.
    """
    from bootstrap_immunization import apply
    import subprocess as _sp

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "master")
    _git(repo, "config", "user.email", "t@test.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "README").write_text("hello\n")
    _git(repo, "add", "README")
    _git(repo, "commit", "-m", "init")

    # core.bare is not set (healthy) — apply() must succeed without error
    apply(repo)

    # extensions.worktreeConfig must be set (normal apply path ran)
    wc = _sp.run(
        ["git", "config", "--local", "extensions.worktreeConfig"],
        cwd=repo, capture_output=True, text=True, env=_GIT_ENV,
    ).stdout.strip()
    assert wc.lower() == "true", (
        f"apply() must set extensions.worktreeConfig=true; got {wc!r}"
    )


# ---------------------------------------------------------------------------
# status CLI catches corrupt-config RuntimeError → {"error": ...} exit 0
# ---------------------------------------------------------------------------


def test_status_function_catches_runtime_error(tmp_path, monkeypatch):
    """status() catches RuntimeError from corrupt config → returns error dict.

    The status() function documents 'Exits 0 always'.  If _read_config raises
    RuntimeError (corrupt JSON), status() must return {"error": ..., ...}
    rather than letting the exception propagate.

    Mutation-verify: removing the try/except in status() causes this test
    to fail with an unhandled RuntimeError.
    """
    from bootstrap_immunization import status

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "master")
    _git(repo, "config", "user.email", "t@test.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "README").write_text("hello\n")
    _git(repo, "add", "README")
    _git(repo, "commit", "-m", "init")

    import bootstrap_immunization as bi

    def raise_runtime(*a, **kw):
        raise RuntimeError("simulated corrupt config")

    # Patch _extensions_worktree_config_set to raise
    monkeypatch.setattr(bi, "_extensions_worktree_config_set", raise_runtime)

    result = status(repo)

    assert "error" in result, (
        "status() must return {'error': ...} on RuntimeError from config read"
    )
    assert result["worktree_config"] is False, (
        "worktree_config must be False when error occurs"
    )
    assert result["heal_hooks"] is False, (
        "heal_hooks must be False when error occurs"
    )
