"""Tests for branch_protection_check.py — first-run.md §Branch-protection detection helper.

Covers the three programmable branches:
- no-origin silent skip
- gh missing fail-open (writes config, prints manual command)
- --auto skip + log (decisions.md entry, no config change, no prompt)

Run with: pytest skills/_shared/test_branch_protection.py -q
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import branch_protection_check
from branch_protection_check import check


def _git_init(repo: Path, with_origin: bool = True) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=repo, check=True)
    if with_origin:
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:Acme/widget.git"],
            cwd=repo,
            check=True,
        )


def test_no_origin_remote_silent_skip(tmp_path: Path, capsys, monkeypatch):
    """git remote get-url origin fails → no prompt, no config write, no stdout."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init(repo, with_origin=False)
    # Pretend gh is present so the test isolates the no-origin branch
    # from the gh-missing branch.
    monkeypatch.setattr(branch_protection_check, "_gh_available", lambda: True)

    result = check(repo=repo, auto=False)

    captured = capsys.readouterr()
    assert result.action == "skip-no-origin"
    assert result.config_updated is False
    assert "gh api" not in captured.out
    assert "Apply GitHub branch protection" not in captured.out
    config_path = repo / ".three-pillars" / "config.json"
    assert not config_path.exists()


def test_gh_missing_writes_fail_open_config_and_prints_manual_command(
    tmp_path: Path, capsys, monkeypatch
):
    """gh absent → declined=false, applied_at=null, offered_at set, stdout has gh api command."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init(repo, with_origin=True)
    monkeypatch.setattr(branch_protection_check, "_gh_available", lambda: False)

    result = check(repo=repo, auto=False)

    captured = capsys.readouterr()
    assert result.action == "fail-open-gh-missing"
    assert result.config_updated is True
    assert "gh api -X PUT" in captured.out
    assert "branches/" in captured.out
    assert "/protection" in captured.out
    assert "required_approving_review_count" in captured.out

    config_path = repo / ".three-pillars" / "config.json"
    assert config_path.exists()
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    bp = data["branch_protection"]
    assert bp["declined"] is False
    assert bp["applied_at"] is None
    assert bp["offered_at"] is not None
    # ISO 8601 UTC sanity
    assert bp["offered_at"].endswith("Z")


def test_auto_mode_skips_protection_and_logs_decision(tmp_path: Path, capsys, monkeypatch):
    """--auto → no prompt, decisions.md gets a [first-run] entry, config untouched."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init(repo, with_origin=True)
    # gh availability is irrelevant under --auto.
    monkeypatch.setattr(branch_protection_check, "_gh_available", lambda: True)

    decisions = repo / "decisions.md"
    result = check(repo=repo, auto=True, decisions_file=decisions)

    captured = capsys.readouterr()
    assert result.action == "auto-skip"
    assert result.config_updated is False
    assert "Apply GitHub branch protection" not in captured.out
    assert decisions.exists()
    body = decisions.read_text(encoding="utf-8")
    assert "[first-run]" in body
    # auto-mode.md schema: every entry has the four labelled lines.
    for label in ("**Question**:", "**Decided**:", "**Reasoning**:", "**Confidence**:"):
        assert label in body, f"decisions.md missing {label}"

    config_path = repo / ".three-pillars" / "config.json"
    assert not config_path.exists()
