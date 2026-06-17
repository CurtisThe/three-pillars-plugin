"""Tests for bootstrap_immunization.py — linked-worktree common-dir behaviour.

Pins the invariant that apply() and status() resolve hooks via
git rev-parse --git-common-dir so that linked-worktree callers install
into the SEAT's real .git/hooks dir, not the dead per-worktree path.

Run with: python -m pytest skills/_shared/test_bootstrap_immunization_worktree.py -q
"""
from __future__ import annotations

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
def linked_worktree_fixture(tmp_path):
    """Create a main repo + a linked worktree; return (main_repo, worktree_path)."""
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-b", "master")
    _git(main, "config", "user.email", "t@test.com")
    _git(main, "config", "user.name", "T")
    _git(main, "config", "commit.gpgsign", "false")
    (main / "README").write_text("hello\n")
    _git(main, "add", "README")
    _git(main, "commit", "-m", "init")

    # Create a linked worktree
    wt = tmp_path / "wt"
    _git(main, "worktree", "add", str(wt), "-b", "tp/linked")

    return main, wt


# ---------------------------------------------------------------------------
# Linked-worktree common-dir tests
# ---------------------------------------------------------------------------


def test_apply_from_linked_worktree_installs_into_main_hooks(linked_worktree_fixture):
    """apply() called from a linked worktree installs hooks into main .git/hooks.

    Before the fix, _hooks_dir() resolved to .git/worktrees/<name>/hooks which
    git never consults.  Now it uses git rev-parse --git-common-dir to find
    the seat's real hooks dir.
    """
    from bootstrap_immunization import apply, HOOK_EVENTS, SENTINEL_BEGIN

    main_repo, worktree = linked_worktree_fixture

    # Apply from the LINKED worktree
    apply(worktree)

    # Hooks must be in the MAIN repo's .git/hooks, not the dead worktree path
    main_hooks = main_repo / ".git" / "hooks"
    for event in HOOK_EVENTS:
        hook_file = main_hooks / event
        assert hook_file.exists(), (
            f"Hook {event!r} missing from main .git/hooks after apply() from worktree"
        )
        content = hook_file.read_bytes().decode("utf-8", errors="replace")
        assert SENTINEL_BEGIN in content, (
            f"Sentinel missing from main .git/hooks/{event} after apply() from worktree"
        )

    # Dead per-worktree hooks path must NOT contain the sentinel
    wt_git_file = worktree / ".git"
    if wt_git_file.is_file():
        gitdir_content = wt_git_file.read_text().strip()
        if gitdir_content.startswith("gitdir:"):
            dead_hooks = Path(gitdir_content.split(":", 1)[1].strip()) / "hooks"
            if dead_hooks.exists():
                for event in HOOK_EVENTS:
                    dead_hook = dead_hooks / event
                    if dead_hook.exists():
                        dead_content = dead_hook.read_bytes().decode("utf-8", errors="replace")
                        assert SENTINEL_BEGIN not in dead_content, (
                            f"Sentinel must NOT be in dead worktree hooks path {dead_hooks}"
                        )


def test_status_from_linked_worktree_reads_main_hooks(linked_worktree_fixture):
    """status() from a linked worktree reports heal_hooks based on main .git/hooks.

    After apply() from the main repo, status() from the linked worktree should
    report heal_hooks=True because it resolves via common-dir.
    """
    from bootstrap_immunization import apply, status

    main_repo, worktree = linked_worktree_fixture

    # Apply from MAIN repo
    apply(main_repo)

    # Status from LINKED worktree must see the installed hooks
    s = status(worktree)
    assert s["heal_hooks"] is True, (
        "status() from linked worktree must report heal_hooks=True after "
        "apply() installed hooks in main .git/hooks"
    )


def test_git_common_dir_resolves_correctly(linked_worktree_fixture):
    """_git_common_dir() returns the main .git directory from a linked worktree."""
    from bootstrap_immunization import _git_common_dir

    main_repo, worktree = linked_worktree_fixture

    common = _git_common_dir(worktree)
    assert common is not None, "_git_common_dir must not return None from a worktree"
    assert common.is_dir(), f"Common dir {common!r} must be an existing directory"

    # Must point at main .git, not the dead worktrees/<name> path
    main_git = main_repo / ".git"
    assert common.resolve() == main_git.resolve(), (
        f"_git_common_dir from linked worktree must resolve to main .git "
        f"({main_git}), got {common}"
    )


def test_read_config_raises_on_corrupt_file(tmp_path):
    """_read_config raises RuntimeError on corrupt config.json (never silently rewrites).

    Before the fix, a corrupt config was silently replaced with the default
    {'schema_version': 1}, clobbering existing migration and branch_protection
    records and causing settled first-run decisions to re-prompt.
    """
    import subprocess
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)

    from bootstrap_immunization import _read_config

    config_dir = tmp_path / ".three-pillars"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "config.json"
    config_path.write_text("this is not valid JSON {{{{")

    with pytest.raises(RuntimeError, match="Corrupt config"):
        _read_config(tmp_path)

    # Original corrupt file must still be there (not rewritten)
    assert config_path.read_text() == "this is not valid JSON {{{{", (
        "_read_config must not rewrite the corrupt file"
    )


def test_hook_has_sentinel_tolerates_binary_hook(tmp_path):
    """_hook_has_sentinel reads bytes with errors='replace' for binary hooks."""
    import subprocess
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)

    from bootstrap_immunization import _hook_has_sentinel

    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    binary_hook = hooks_dir / "post-checkout"
    # Write a non-UTF-8 binary blob
    binary_hook.write_bytes(b"\xff\xfe\x00binary content\x00")

    # Must not raise UnicodeDecodeError
    result = _hook_has_sentinel(binary_hook)
    assert result is False, "Binary hook without sentinel must return False"
