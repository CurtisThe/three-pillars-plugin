"""Tests for _load_repo_config project-root re-rooting (W4 provenance).

Core regression test: _load_repo_config() reads from the cwd's git repo
(the project under operation), NOT from the framework checkout that hosts
the gate module. This is the cross-project fail-open class the design closes.

Test strategy: real git operations in tmp dirs, monkeypatched cwd, no
subprocess mocking — suite convention.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_repo_with_config(path: Path, config: dict) -> None:
    """Create a git repo at path with a committed .three-pillars/config.json."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test.com"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"],
        check=True, capture_output=True,
    )
    cfg_dir = path / ".three-pillars"
    cfg_dir.mkdir()
    cfg_file = cfg_dir / "config.json"
    cfg_file.write_text(json.dumps(config))
    subprocess.run(
        ["git", "-C", str(path), "add", ".three-pillars/config.json"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init config"],
        check=True, capture_output=True,
    )


def _init_empty_repo(path: Path) -> None:
    """Create a git repo at path with no .three-pillars/config.json."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test.com"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"],
        check=True, capture_output=True,
    )
    # Need at least one commit
    sentinel = path / "README"
    sentinel.write_text("init")
    subprocess.run(
        ["git", "-C", str(path), "add", "README"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init"],
        check=True, capture_output=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_committed_config_read_from_cwd_repo(tmp_path, monkeypatch):
    """cwd inside a project repo with committed config → that config returned."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from deterministic_gate import _load_repo_config

    project_config = {"ci": {"expects_github_checks": False}, "custom_key": "from_project"}
    project = tmp_path / "consumer_project"
    _init_repo_with_config(project, project_config)

    monkeypatch.chdir(project)
    result = _load_repo_config()
    assert result.get("custom_key") == "from_project"
    assert result["ci"]["expects_github_checks"] is False


def test_uncommitted_edit_invisible(tmp_path, monkeypatch):
    """W4 regression pin: uncommitted edits to config.json are invisible.

    The committed config carries a distinctive marker key
    ('committed_marker_w4_pin') absent from the working-tree edit, so the
    assertion independently distinguishes the project-HEAD read from any
    fallback to the framework-HEAD or working-tree.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from deterministic_gate import _load_repo_config

    # Distinctive marker key absent from the working-tree version
    project_config = {
        "ci": {"expects_github_checks": False},
        "committed_marker_w4_pin": "committed",
    }
    project = tmp_path / "consumer_project"
    _init_repo_with_config(project, project_config)

    # Modify working tree without committing — replaces the committed config
    cfg_file = project / ".three-pillars" / "config.json"
    modified = {"ci": {"expects_github_checks": True}, "sneaky_edit": True}
    cfg_file.write_text(json.dumps(modified))

    monkeypatch.chdir(project)
    result = _load_repo_config()
    # Must see the committed version, not the working-tree edit
    assert result.get("sneaky_edit") is None, (
        "Working-tree edit must not be visible (HEAD read only)"
    )
    assert result.get("committed_marker_w4_pin") == "committed", (
        "Committed marker key must be present — confirms project-HEAD was read"
    )
    assert result["ci"]["expects_github_checks"] is False, (
        "Committed expects_github_checks must be False"
    )


def test_non_repo_cwd_returns_empty(tmp_path, monkeypatch):
    """cwd in a non-repo directory → {} (fail-closed)."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from deterministic_gate import _load_repo_config

    non_repo = tmp_path / "not_a_repo"
    non_repo.mkdir()
    monkeypatch.chdir(non_repo)

    result = _load_repo_config()
    assert result == {}


# ---------------------------------------------------------------------------
# Binding-check tests: evaluate_gate config-root → PR-owner/repo match
# ---------------------------------------------------------------------------

_HERMETIC_RUNNERS_BASE = {
    "pr_state_fn": lambda url: {
        "mergeable": "MERGEABLE",
        "headRefOid": "deadbeef",
        "statusCheckRollup": [],
    },
    "threads_fn": lambda url: [],
    "labels_fn": lambda url: [],
    "timeline_fn": lambda url: [],
    "head_fn": lambda url: {},
    "commits_fn": lambda url: [],
    "self_login_fn": lambda: "bot",
}

_RELAXED_CONFIG = {
    "ci": {"expects_github_checks": False},
    "review": {"expects_copilot": False, "require_human_approval": False},
}


def test_binding_matching_remote_uses_config(tmp_path, monkeypatch):
    """Config root whose remote matches the PR repo → relaxed config IS honored.

    EFFECT assertion (mutation-grade): the relaxed config (expects_copilot=False,
    expects_github_checks=False) must be reflected in the gate outcome. If the
    binding incorrectly falls back to strict defaults, copilot_on_head would
    appear as INDETERMINATE (not OMITTED) and human_approved would be required
    instead of omitted.

    Mutation pin: deleting the config={} line in the mismatch branch (making the
    code always use strict defaults) would make the match case behave like the
    mismatch case — this test catches that mutation.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from deterministic_gate import evaluate_gate

    project = tmp_path / "project"
    _init_repo_with_config(project, _RELAXED_CONFIG)
    monkeypatch.chdir(project)

    # remote_url_fn returns the SAME owner/repo as the PR URL
    def matching_remote(_cmd):
        return "https://github.com/o/r.git"

    runners = dict(_HERMETIC_RUNNERS_BASE, remote_url_fn=matching_remote)
    outcome = evaluate_gate(
        "https://github.com/o/r/pull/1",
        runners=runners,
    )
    # config_root_binding should NOT appear in roster when match succeeds
    binding_entries = [e for e in (outcome.roster or ()) if e.name == "config_root_binding"]
    assert not binding_entries, (
        f"Unexpected config_root_binding entry on matching remote: {binding_entries}"
    )
    # EFFECT: relaxed config must be honored — expects_copilot=False → OMITTED
    copilot_entries = [e for e in (outcome.roster or ()) if e.name == "copilot_on_head"]
    assert len(copilot_entries) == 1, (
        f"Expected one copilot_on_head roster entry; got {copilot_entries}"
    )
    assert copilot_entries[0].status == "OMITTED", (
        f"Expected copilot_on_head=OMITTED (config honored: expects_copilot=False), "
        f"got {copilot_entries[0].status!r}. "
        "Mutation pin: if config is not honored the relaxed expects_copilot=False "
        "would not be seen and copilot_on_head would not be omitted."
    )
    # EFFECT: require_human_approval=False → human_approved OMITTED
    human_entries = [e for e in (outcome.roster or ()) if e.name == "human_approved"]
    assert len(human_entries) == 1, (
        f"Expected one human_approved roster entry; got {human_entries}"
    )
    assert human_entries[0].status == "OMITTED", (
        f"Expected human_approved=OMITTED (config honored: require_human_approval=False), "
        f"got {human_entries[0].status!r}."
    )


def test_binding_mismatched_remote_strict_defaults(tmp_path, monkeypatch):
    """Config root whose remote DIFFERS from the PR repo → config ignored, strict defaults.

    NON-BLOCKING semantics: the mismatch note is roster-only (informational).
    The strict defaults (config={}) are the protection — the gate may still PASS
    if all strict-default predicates pass (e.g. in hermetic tests).

    EFFECT assertions (mutation-grade): strict defaults mean copilot_on_head is
    evaluated (NOT omitted) since _expects_copilot_review({}) returns True.
    Mutation pin: deleting the config={} line in the mismatch branch would honor
    the relaxed config, making copilot_on_head appear as OMITTED — caught here.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from deterministic_gate import evaluate_gate

    project = tmp_path / "project"
    _init_repo_with_config(project, _RELAXED_CONFIG)
    monkeypatch.chdir(project)

    # remote_url_fn returns a DIFFERENT owner/repo than the PR URL
    def mismatched_remote(_cmd):
        return "https://github.com/other-owner/other-repo.git"

    runners = dict(_HERMETIC_RUNNERS_BASE, remote_url_fn=mismatched_remote)
    outcome = evaluate_gate(
        "https://github.com/o/r/pull/1",
        runners=runners,
    )
    # Informational note in roster only
    binding_entries = [e for e in (outcome.roster or ()) if e.name == "config_root_binding"]
    assert len(binding_entries) == 1, (
        f"Expected one config_root_binding roster entry; got {binding_entries}"
    )
    assert binding_entries[0].status == "INDETERMINATE", (
        f"Expected INDETERMINATE, got {binding_entries[0].status}"
    )
    assert "does not match" in binding_entries[0].detail.lower(), (
        f"Detail must mention mismatch: {binding_entries[0].detail!r}"
    )
    # NON-BLOCKING: the note must NOT appear in blocking predicates
    blocking_names = [p.name for p in (outcome.blocking or [])]
    assert "config_root_binding" not in blocking_names, (
        f"config_root_binding must not fold into blocking predicates "
        f"(non-blocking semantics): blocking={blocking_names}"
    )
    # EFFECT: strict defaults in effect — copilot_on_head is EVALUATED (not OMITTED).
    # With _RELAXED_CONFIG's expects_copilot=False, if config were honored the
    # predicate would be OMITTED. Strict defaults → expects_copilot=True → evaluated.
    copilot_entries = [e for e in (outcome.roster or ()) if e.name == "copilot_on_head"]
    assert len(copilot_entries) == 1, (
        f"Expected one copilot_on_head roster entry; got {copilot_entries}"
    )
    assert copilot_entries[0].status != "OMITTED", (
        f"copilot_on_head must NOT be OMITTED under strict defaults "
        f"(mismatch → config={{}}, expects_copilot defaults to True). "
        "Mutation pin: deleting config={{}} in mismatch branch would honor the "
        "relaxed config, setting copilot_on_head=OMITTED — caught here."
    )


def test_binding_unreadable_remote_strict_defaults(tmp_path, monkeypatch):
    """Config root with no readable remote → config ignored, strict defaults, roster note.

    NON-BLOCKING semantics: the note is roster-only (informational).
    EFFECT assertion: strict defaults apply → copilot_on_head is evaluated (not omitted).
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from deterministic_gate import evaluate_gate

    project = tmp_path / "project"
    _init_repo_with_config(project, _RELAXED_CONFIG)
    monkeypatch.chdir(project)

    # remote_url_fn raises to simulate no remote configured
    def unreadable_remote(_cmd):
        raise RuntimeError("no remote 'origin' configured")

    runners = dict(_HERMETIC_RUNNERS_BASE, remote_url_fn=unreadable_remote)
    outcome = evaluate_gate(
        "https://github.com/o/r/pull/1",
        runners=runners,
    )
    binding_entries = [e for e in (outcome.roster or ()) if e.name == "config_root_binding"]
    assert len(binding_entries) == 1, (
        f"Expected one config_root_binding roster entry; got {binding_entries}"
    )
    assert binding_entries[0].status == "INDETERMINATE"
    # NON-BLOCKING: note must not fold into blocking predicates
    blocking_names = [p.name for p in (outcome.blocking or [])]
    assert "config_root_binding" not in blocking_names, (
        f"config_root_binding must not fold into blocking predicates: {blocking_names}"
    )
    # EFFECT: strict defaults → copilot_on_head evaluated (not omitted)
    copilot_entries = [e for e in (outcome.roster or ()) if e.name == "copilot_on_head"]
    assert len(copilot_entries) == 1
    assert copilot_entries[0].status != "OMITTED", (
        f"copilot_on_head must NOT be OMITTED under strict defaults (unreadable remote): "
        f"got {copilot_entries[0].status!r}"
    )


def test_cross_project_fail_open_pin(tmp_path, monkeypatch):
    """Core regression: cwd in a repo WITHOUT config returns {} even if the
    framework checkout has its own config.

    This is the primary invariant of the design: the gate reads the PROJECT's
    config, not the framework's. A consumer project that has no config must
    never inherit the framework's settings.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from deterministic_gate import _load_repo_config

    # Consumer project: git repo but no .three-pillars/config.json
    consumer = tmp_path / "consumer"
    _init_empty_repo(consumer)

    monkeypatch.chdir(consumer)
    result = _load_repo_config()
    # Must be empty — consumer has no config at HEAD
    assert result == {}
