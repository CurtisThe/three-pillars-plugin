"""Tests for the bootstrap_immunization CLI entrypoint (main() / __main__).

Pins Task: bootstrap_immunization CLI — first-run prose now invocable.

Invariants:
  - `status` subcommand exits 0 and emits parseable JSON with expected keys
  - `status` JSON includes worktree_config, heal_hooks, and cheap_check fields
  - `apply` subcommand exits 0 on a valid repo and installs immunization
  - `apply` subcommand does NOT prompt the user (no-prompt contract)
  - `--help` exits 0 (standard argparse behaviour)
  - Unknown subcommand exits non-zero (standard argparse behaviour)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures — reuse the same minimal-git-repo pattern as the sibling suite
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
    (tmp_path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    return tmp_path


# Path to the module under test (absolute, so subprocess invocation works from
# any cwd).
_MODULE = Path(__file__).parent / "bootstrap_immunization.py"


def _run_cli(*args, cwd=None):
    """Run bootstrap_immunization.py as a subprocess and return CompletedProcess."""
    return subprocess.run(
        [sys.executable, str(_MODULE), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# status subcommand
# ---------------------------------------------------------------------------


def test_cli_status_exits_zero(tmp_git_repo):
    """`status` subcommand exits 0."""
    result = _run_cli("--repo", str(tmp_git_repo), "status")
    assert result.returncode == 0, f"stderr: {result.stderr}"


def test_cli_status_emits_valid_json(tmp_git_repo):
    """`status` output is parseable JSON."""
    result = _run_cli("--repo", str(tmp_git_repo), "status")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert isinstance(data, dict)


def test_cli_status_json_has_expected_keys(tmp_git_repo):
    """`status` JSON contains worktree_config, heal_hooks, and cheap_check."""
    result = _run_cli("--repo", str(tmp_git_repo), "status")
    data = json.loads(result.stdout)
    assert "worktree_config" in data, "Missing key: worktree_config"
    assert "heal_hooks" in data, "Missing key: heal_hooks"
    assert "cheap_check" in data, "Missing key: cheap_check"


def test_cli_status_fresh_repo_shows_false_and_needs_prompt(tmp_git_repo):
    """`status` on a fresh repo reports false/false/needs-prompt."""
    result = _run_cli("--repo", str(tmp_git_repo), "status")
    data = json.loads(result.stdout)
    assert data["worktree_config"] is False
    assert data["heal_hooks"] is False
    assert data["cheap_check"] == "needs-prompt"


def test_cli_status_after_apply_shows_true_and_skip_decided(tmp_git_repo):
    """`status` after CLI apply shows worktree_config=true and skip-decided."""
    apply_result = _run_cli("--repo", str(tmp_git_repo), "apply")
    assert apply_result.returncode == 0, f"apply failed: {apply_result.stderr}"

    result = _run_cli("--repo", str(tmp_git_repo), "status")
    data = json.loads(result.stdout)
    assert data["worktree_config"] is True
    assert data["heal_hooks"] is True
    assert data["cheap_check"] == "skip-decided"


# ---------------------------------------------------------------------------
# apply subcommand
# ---------------------------------------------------------------------------


def test_cli_apply_exits_zero(tmp_git_repo):
    """`apply` subcommand exits 0 on a valid repo."""
    result = _run_cli("--repo", str(tmp_git_repo), "apply")
    assert result.returncode == 0, f"stderr: {result.stderr}"


def test_cli_apply_writes_config_record(tmp_git_repo):
    """`apply` writes applied_at into the repo config."""
    _run_cli("--repo", str(tmp_git_repo), "apply")
    config_path = tmp_git_repo / ".three-pillars" / "config.json"
    assert config_path.exists(), "config.json not written"
    data = json.loads(config_path.read_text())
    wi = data.get("worktree_immunization", {})
    assert wi.get("applied_at") is not None, "applied_at not recorded"
    assert wi.get("declined") is False


def test_cli_apply_installs_hooks(tmp_git_repo):
    """`apply` installs the heal hooks into .git/hooks/."""
    _run_cli("--repo", str(tmp_git_repo), "apply")
    hooks_dir = tmp_git_repo / ".git" / "hooks"
    for event in ("post-checkout", "post-merge"):
        hook_file = hooks_dir / event
        assert hook_file.exists(), f"Hook file {event} not installed"
        assert "heal-core-bare" in hook_file.read_text() or "three-pillars" in hook_file.read_text(), (
            f"Sentinel content missing from {event}"
        )


def test_cli_apply_is_idempotent(tmp_git_repo):
    """`apply` called twice exits 0 both times with no duplicate sentinels."""
    r1 = _run_cli("--repo", str(tmp_git_repo), "apply")
    r2 = _run_cli("--repo", str(tmp_git_repo), "apply")
    assert r1.returncode == 0
    assert r2.returncode == 0
    hooks_dir = tmp_git_repo / ".git" / "hooks"
    sentinel = "# three-pillars: heal-core-bare BEGIN"
    for event in ("post-checkout", "post-merge"):
        content = (hooks_dir / event).read_text()
        assert content.count(sentinel) == 1, f"Sentinel duplicated in {event}"


def test_cli_apply_does_not_prompt(tmp_git_repo):
    """`apply` must not read from stdin (no TTY prompt)."""
    # Run with stdin closed (no interactive terminal available)
    result = subprocess.run(
        [sys.executable, str(_MODULE), "--repo", str(tmp_git_repo), "apply"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        f"apply with closed stdin failed: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# Misc / edge cases
# ---------------------------------------------------------------------------


def test_cli_help_exits_zero():
    """`--help` exits 0."""
    result = _run_cli("--help")
    assert result.returncode == 0


def test_cli_status_help_exits_zero():
    """`status --help` exits 0."""
    result = _run_cli("status", "--help")
    assert result.returncode == 0


def test_cli_unknown_subcommand_exits_nonzero():
    """Unknown subcommand produces a non-zero exit."""
    result = _run_cli("unknown-subcommand-xyz")
    assert result.returncode != 0


def test_cli_status_repo_after_subcommand_order(tmp_git_repo):
    """`status --repo <path>` order (subcommand first, then --repo) works.

    The original CLI had --repo only on the main parser, so argparse rejected
    it when placed after the subcommand name.  The fix adds --repo to each
    subparser so both orders are valid.
    """
    result = _run_cli("status", "--repo", str(tmp_git_repo))
    assert result.returncode == 0, (
        f"`status --repo <path>` failed: {result.stderr!r}"
    )
    import json
    data = json.loads(result.stdout)
    assert "worktree_config" in data


def test_cli_apply_repo_after_subcommand_order(tmp_git_repo):
    """`apply --repo <path>` order works (subcommand first, then --repo)."""
    result = _run_cli("apply", "--repo", str(tmp_git_repo))
    assert result.returncode == 0, (
        f"`apply --repo <path>` failed: {result.stderr!r}"
    )
