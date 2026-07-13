"""Tests for skills/_shared/bootstrap_immunization.py.

Covers Task 3.1 (installer + heal hook) and Task 3.2 (config record).

Key invariants:
  - status() reports correct worktree_config and heal_hooks state
  - apply() sets extensions.worktreeConfig=true and installs heal hooks
  - Sentinel-guarded append: never clobbers existing hook content
  - Idempotent: second apply() changes nothing
  - Heal hook: no-op on healthy repo; flips core.bare on bleed state
  - cheap_check(): 'skip-decided' when applied_at non-null or declined=true
  - cheap_check(): 'needs-prompt' when no prior decision
  - mark_applied() / mark_declined(): atomic writes; suppress reprompt
  - Schema: worktree_immunization block {offered_at, applied_at, declined}
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_git_repo(tmp_path):
    """A minimal git repo in tmp_path."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    # Initial commit so HEAD exists
    (tmp_path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    return tmp_path


@pytest.fixture()
def repo(tmp_git_repo):
    """Alias for tmp_git_repo that imports the module under test."""
    import importlib, sys
    # Ensure the _shared path is importable from the test's perspective
    here = Path(__file__).parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    return tmp_git_repo


# ---------------------------------------------------------------------------
# Task 3.1: status() / apply() / sentinel / idempotence / heal-hook
# ---------------------------------------------------------------------------


def test_status_fresh_repo_returns_false_false(repo):
    """A fresh repo has neither worktree_config nor heal_hooks installed."""
    from bootstrap_immunization import status
    s = status(repo)
    assert s["worktree_config"] is False
    assert s["heal_hooks"] is False


def test_apply_sets_extensions_worktree_config(repo):
    """apply() sets extensions.worktreeConfig=true in .git/config."""
    from bootstrap_immunization import apply, status
    apply(repo)
    s = status(repo)
    assert s["worktree_config"] is True


def test_apply_installs_heal_hooks(repo):
    """apply() installs the heal hook in post-checkout and post-merge."""
    from bootstrap_immunization import apply, status, HOOK_EVENTS, SENTINEL_BEGIN
    apply(repo)
    s = status(repo)
    assert s["heal_hooks"] is True
    # Verify sentinels are in the actual files
    hooks_dir = repo / ".git" / "hooks"
    for event in HOOK_EVENTS:
        hook_file = hooks_dir / event
        assert hook_file.exists(), f"Hook file {event} missing"
        content = hook_file.read_text(encoding="utf-8")
        assert SENTINEL_BEGIN in content, f"Sentinel missing from {event}"


def test_apply_hook_files_are_executable(repo):
    """apply() ensures hook files are executable."""
    from bootstrap_immunization import apply, HOOK_EVENTS
    apply(repo)
    hooks_dir = repo / ".git" / "hooks"
    for event in HOOK_EVENTS:
        hook_file = hooks_dir / event
        assert hook_file.stat().st_mode & 0o111, f"{event} not executable"


def test_apply_is_idempotent(repo):
    """Second apply() changes nothing (idempotent re-apply)."""
    from bootstrap_immunization import apply, HOOK_EVENTS, SENTINEL_BEGIN, SENTINEL_END
    apply(repo)
    hooks_dir = repo / ".git" / "hooks"
    # Record content after first apply
    contents_after_first = {}
    for event in HOOK_EVENTS:
        contents_after_first[event] = (hooks_dir / event).read_text(encoding="utf-8")

    apply(repo)
    # Content must be identical after second apply
    for event in HOOK_EVENTS:
        assert (hooks_dir / event).read_text(encoding="utf-8") == contents_after_first[event], (
            f"Hook {event} changed on second apply (not idempotent)"
        )
    # Sentinel appears exactly once
    for event in HOOK_EVENTS:
        content = (hooks_dir / event).read_text(encoding="utf-8")
        assert content.count(SENTINEL_BEGIN) == 1, (
            f"Sentinel duplicated in {event} after re-apply"
        )


def test_apply_does_not_clobber_existing_hook(repo):
    """apply() appends to an existing hook file — never clobbers it."""
    from bootstrap_immunization import apply, HOOK_EVENTS
    hooks_dir = repo / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    existing_body = "#!/usr/bin/env bash\necho 'existing hook'\n"
    for event in HOOK_EVENTS:
        hook_file = hooks_dir / event
        hook_file.write_text(existing_body)
        hook_file.chmod(0o755)

    apply(repo)
    for event in HOOK_EVENTS:
        content = (hooks_dir / event).read_text(encoding="utf-8")
        assert "existing hook" in content, (
            f"apply() clobbered the existing {event} hook"
        )


def test_heal_hook_is_noop_on_healthy_repo(repo):
    """The heal script exits 0 on a normal (non-bleed) repo without changing anything."""
    from bootstrap_immunization import apply
    apply(repo)
    hooks_dir = repo / ".git" / "hooks"
    heal_hook = hooks_dir / "post-checkout"
    result = subprocess.run(
        ["bash", str(heal_hook)],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Heal hook failed on healthy repo: {result.stderr}"
    # core.bare should still be false (or unset)
    bare_result = subprocess.run(
        ["git", "config", "--local", "core.bare"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    # Either unset or explicitly false is healthy
    bare_val = bare_result.stdout.strip().lower()
    assert bare_val in ("false", ""), f"core.bare unexpectedly set to {bare_val!r}"


def test_heal_hook_flips_core_bare_on_bleed_state(repo):
    """The heal script flips core.bare from true→false when .git/ subdir is present."""
    from bootstrap_immunization import apply
    apply(repo)
    hooks_dir = repo / ".git" / "hooks"
    heal_hook = hooks_dir / "post-checkout"

    # Simulate the bleed state: set core.bare=true on a non-bare checkout
    subprocess.run(
        ["git", "config", "--local", "core.bare", "true"],
        cwd=repo, check=True, capture_output=True,
    )

    result = subprocess.run(
        ["bash", str(heal_hook)],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Heal hook failed: {result.stderr}"

    # core.bare must now be false
    bare_result = subprocess.run(
        ["git", "config", "--local", "core.bare"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert bare_result.stdout.strip().lower() == "false", (
        "heal hook did not flip core.bare back to false"
    )


def test_apply_only_called_by_consent_apply_never_auto_runs(repo):
    """Module import does NOT call apply() — it must be invoked explicitly."""
    import importlib
    # Importing the module must not touch the repo
    import bootstrap_immunization  # noqa: F401
    s_before = {}
    s_before["worktree_config"] = subprocess.run(
        ["git", "config", "--local", "extensions.worktreeConfig"],
        cwd=repo, capture_output=True, text=True,
    ).stdout.strip()
    # Re-import (no-op on second import if already cached)
    importlib.reload(__import__("bootstrap_immunization"))
    s_after = subprocess.run(
        ["git", "config", "--local", "extensions.worktreeConfig"],
        cwd=repo, capture_output=True, text=True,
    ).stdout.strip()
    assert s_before["worktree_config"] == s_after, "apply() was called on import"


# ---------------------------------------------------------------------------
# Task 3.2: Config record — cheap_check / mark_applied / mark_declined
# ---------------------------------------------------------------------------


def test_cheap_check_needs_prompt_on_fresh_repo(repo):
    """cheap_check returns 'needs-prompt' when no prior decision recorded."""
    from bootstrap_immunization import cheap_check
    assert cheap_check(repo) == "needs-prompt"


def test_cheap_check_skip_decided_when_applied(repo):
    """cheap_check returns 'skip-decided' after mark_applied."""
    from bootstrap_immunization import cheap_check, mark_applied
    mark_applied(repo)
    assert cheap_check(repo) == "skip-decided"


def test_cheap_check_skip_decided_when_declined(repo):
    """cheap_check returns 'skip-decided' after mark_declined."""
    from bootstrap_immunization import cheap_check, mark_declined
    mark_declined(repo)
    assert cheap_check(repo) == "skip-decided"


def test_mark_applied_writes_applied_at(repo):
    """mark_applied() writes a non-null applied_at ISO timestamp."""
    from bootstrap_immunization import mark_applied
    mark_applied(repo)
    config = json.loads((repo / ".three-pillars" / "config.json").read_text(encoding="utf-8"))
    wi = config.get("worktree_immunization", {})
    assert wi.get("applied_at") is not None
    assert "T" in wi["applied_at"], "applied_at not ISO format"
    assert wi.get("declined") is False


def test_mark_declined_writes_declined_true(repo):
    """mark_declined() writes declined=true and applied_at=null."""
    from bootstrap_immunization import mark_declined
    mark_declined(repo)
    config = json.loads((repo / ".three-pillars" / "config.json").read_text(encoding="utf-8"))
    wi = config.get("worktree_immunization", {})
    assert wi.get("declined") is True
    assert wi.get("applied_at") is None


def test_mark_applied_idempotent_does_not_overwrite_offered_at(repo):
    """mark_applied() preserves offered_at from the initial mark_offered call."""
    from bootstrap_immunization import mark_applied, mark_offered
    mark_offered(repo)
    config1 = json.loads((repo / ".three-pillars" / "config.json").read_text(encoding="utf-8"))
    offered_at_1 = config1["worktree_immunization"]["offered_at"]
    mark_applied(repo)
    config2 = json.loads((repo / ".three-pillars" / "config.json").read_text(encoding="utf-8"))
    # offered_at must be preserved (not reset to now)
    assert config2["worktree_immunization"]["offered_at"] == offered_at_1


def test_config_schema_accepts_worktree_immunization_block(repo):
    """worktree_immunization block round-trips through the repo config cleanly."""
    from bootstrap_immunization import mark_applied
    mark_applied(repo)
    raw = (repo / ".three-pillars" / "config.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    wi = data["worktree_immunization"]
    # All expected keys are present
    assert "offered_at" in wi
    assert "applied_at" in wi
    assert "declined" in wi
    # No extra keys sneaked in
    assert set(wi.keys()) == {"offered_at", "applied_at", "declined"}


def test_config_write_is_atomic(repo, monkeypatch):
    """mark_applied uses tmp-and-rename so a crash mid-write leaves old config intact."""
    from bootstrap_immunization import mark_applied
    config_path = repo / ".three-pillars" / "config.json"
    # Write a valid existing config
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing = {"schema_version": 1}
    config_path.write_text(json.dumps(existing))

    # Simulate a crash mid-write by making fsync raise on the tmp file
    import bootstrap_immunization as bi
    original_fsync = os.fsync

    def bad_fsync(fd):
        raise OSError("simulated crash")

    monkeypatch.setattr(os, "fsync", bad_fsync)
    with pytest.raises(OSError, match="simulated crash"):
        mark_applied(repo)

    # Original file must still be valid
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data == existing, "Original config was overwritten despite simulated crash"
