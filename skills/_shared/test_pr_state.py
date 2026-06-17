"""Tests for pr_state.py — reusable per-branch PR-state predicate.

Run with: python -m pytest skills/_shared/test_pr_state.py -q

Covers:
- merged PR → MERGED with timestamp
- open PR → OPEN
- no PR for branch → NO_PR (positive gh answer, distinct from UNKNOWN)
- gh missing / network error / malformed JSON / non-zero exit → UNKNOWN
- explicitly pins that no branch-existence check is exposed
- rider pin: remote-branch absence is NOT teardown/merge evidence
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import pr_state
from pr_state import PrVerdict, pr_state as get_pr_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_gh_result(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    """Build a fake subprocess.CompletedProcess for mocking."""
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


# ---------------------------------------------------------------------------
# Happy-path verdict tests
# ---------------------------------------------------------------------------

def test_merged_pr_returns_MERGED_with_timestamp(monkeypatch):
    """gh reports a MERGED PR → verdict is MERGED with mergedAt timestamp."""
    payload = json.dumps({
        "state": "MERGED",
        "mergedAt": "2026-05-01T20:00:00Z",
        "number": 70,
        "headRefName": "tp/my-design",
    })
    monkeypatch.setattr(
        pr_state, "_run_gh",
        lambda branch, cwd: _make_gh_result(0, payload),
    )
    v = get_pr_state("tp/my-design")
    assert v.state == "MERGED"
    assert v.merged_at == "2026-05-01T20:00:00Z"
    assert v.evidence is not None


def test_open_pr_returns_OPEN(monkeypatch):
    """gh reports an OPEN PR → verdict is OPEN."""
    payload = json.dumps({
        "state": "OPEN",
        "mergedAt": None,
        "number": 80,
        "headRefName": "tp/open-design",
    })
    monkeypatch.setattr(
        pr_state, "_run_gh",
        lambda branch, cwd: _make_gh_result(0, payload),
    )
    v = get_pr_state("tp/open-design")
    assert v.state == "OPEN"
    assert v.merged_at is None


def test_closed_non_merged_pr_returns_CLOSED(monkeypatch):
    """gh reports a CLOSED (not merged) PR → verdict is CLOSED, not deletable."""
    payload = json.dumps({
        "state": "CLOSED",
        "mergedAt": None,
        "number": 55,
        "headRefName": "tp/closed-design",
    })
    monkeypatch.setattr(
        pr_state, "_run_gh",
        lambda branch, cwd: _make_gh_result(0, payload),
    )
    v = get_pr_state("tp/closed-design")
    assert v.state == "CLOSED"
    assert v.merged_at is None


def test_no_pr_for_branch_returns_NO_PR(monkeypatch):
    """gh returns non-zero exit with 'no pull requests' message → NO_PR (positive answer)."""
    monkeypatch.setattr(
        pr_state, "_run_gh",
        lambda branch, cwd: _make_gh_result(1, "", "no pull requests found"),
    )
    v = get_pr_state("tp/no-pr-branch")
    assert v.state == "NO_PR"
    assert v.merged_at is None


# ---------------------------------------------------------------------------
# Failure path tests — all must produce UNKNOWN, never an exception
# ---------------------------------------------------------------------------

def test_gh_not_on_path_returns_UNKNOWN(monkeypatch):
    """gh binary missing → UNKNOWN."""
    def raise_file_not_found(branch, cwd):
        raise FileNotFoundError("gh not found")

    monkeypatch.setattr(pr_state, "_run_gh", raise_file_not_found)
    v = get_pr_state("tp/some-branch")
    assert v.state == "UNKNOWN"
    assert v.merged_at is None


def test_network_error_subprocess_timeout_returns_UNKNOWN(monkeypatch):
    """subprocess.TimeoutExpired → UNKNOWN."""
    def raise_timeout(branch, cwd):
        raise subprocess.TimeoutExpired(cmd=["gh"], timeout=30)

    monkeypatch.setattr(pr_state, "_run_gh", raise_timeout)
    v = get_pr_state("tp/some-branch")
    assert v.state == "UNKNOWN"


def test_malformed_json_returns_UNKNOWN(monkeypatch):
    """gh returns non-JSON → UNKNOWN."""
    monkeypatch.setattr(
        pr_state, "_run_gh",
        lambda branch, cwd: _make_gh_result(0, "not-json-at-all"),
    )
    v = get_pr_state("tp/some-branch")
    assert v.state == "UNKNOWN"


def test_general_subprocess_exception_returns_UNKNOWN(monkeypatch):
    """Any unexpected subprocess error → UNKNOWN, never raised."""
    def raise_generic(branch, cwd):
        raise OSError("connection reset")

    monkeypatch.setattr(pr_state, "_run_gh", raise_generic)
    v = get_pr_state("tp/some-branch")
    assert v.state == "UNKNOWN"


def test_gh_nonzero_without_no_pr_message_returns_UNKNOWN(monkeypatch):
    """gh non-zero exit that is not a 'no pull requests' reply → UNKNOWN."""
    monkeypatch.setattr(
        pr_state, "_run_gh",
        lambda branch, cwd: _make_gh_result(1, "", "rate limit exceeded"),
    )
    v = get_pr_state("tp/rate-limited")
    assert v.state == "UNKNOWN"


def test_http_404_in_stderr_returns_UNKNOWN(monkeypatch):
    """gh failure with 'HTTP 404: Not Found' in stderr → UNKNOWN, never NO_PR.

    The bare '404' substring was previously in _NO_PR_MARKERS which caused
    genuine gh failures (repo not found, expired auth, SAML-blocked) to be
    classified as the positive NO_PR verdict.  NO_PR is deletion evidence for
    agent branches, so an auth outage could make every agent branch 'deletable'.
    This test pins the fix: 404 errors map to UNKNOWN.
    """
    monkeypatch.setattr(
        pr_state, "_run_gh",
        lambda branch, cwd: _make_gh_result(1, "", "HTTP 404: Not Found"),
    )
    v = get_pr_state("tp/some-branch")
    assert v.state == "UNKNOWN", (
        f"HTTP 404 error must return UNKNOWN, not NO_PR; got {v.state!r}"
    )


def test_404_repo_not_found_returns_UNKNOWN(monkeypatch):
    """gh failure with '404: repository not found' in stderr → UNKNOWN."""
    monkeypatch.setattr(
        pr_state, "_run_gh",
        lambda branch, cwd: _make_gh_result(1, "", "404: repository not found"),
    )
    v = get_pr_state("tp/some-branch")
    assert v.state == "UNKNOWN", (
        f"Repository-not-found 404 must return UNKNOWN; got {v.state!r}"
    )


# ---------------------------------------------------------------------------
# Rider pin: no branch-existence check; docstring states the principle
# ---------------------------------------------------------------------------

def test_module_has_no_branch_existence_check():
    """The module must NOT expose any function that checks for branch existence.

    Remote-branch absence is NOT teardown/merge evidence (GitHub auto-delete-on-merge
    means a remote branch can vanish while the branch is MERGED, not deleted).
    The pr_state module is the authority; branch absence is noise.
    """
    import inspect
    source = inspect.getsource(pr_state)
    # No branch-existence check functions should exist
    assert "branch_exists" not in source
    assert "remote_exists" not in source
    # Verify the docstring explicitly states the principle
    assert "branch absence" in source.lower() or "remote-branch absence" in source.lower()


def test_verdict_dataclass_has_required_fields():
    """PrVerdict must expose state, merged_at, and evidence fields."""
    v = PrVerdict(state="MERGED", merged_at="2026-01-01T00:00:00Z", evidence={"number": 1})
    assert v.state == "MERGED"
    assert v.merged_at == "2026-01-01T00:00:00Z"
    assert v.evidence == {"number": 1}


def test_verdict_state_closed_set():
    """Valid states are exactly: MERGED, OPEN, CLOSED, NO_PR, UNKNOWN."""
    valid_states = {"MERGED", "OPEN", "CLOSED", "NO_PR", "UNKNOWN"}
    # Check that the module exposes VALID_STATES constant or that all test states are there
    if hasattr(pr_state, "VALID_STATES"):
        assert pr_state.VALID_STATES == valid_states


def test_main_cli_outputs_json_line(monkeypatch, capsys):
    """python3 pr_state.py <branch> → a single JSON line on stdout."""
    payload = json.dumps({
        "state": "OPEN",
        "mergedAt": None,
        "number": 99,
        "headRefName": "tp/cli-test",
    })
    monkeypatch.setattr(
        pr_state, "_run_gh",
        lambda branch, cwd: _make_gh_result(0, payload),
    )
    import sys
    monkeypatch.setattr(sys, "argv", ["pr_state.py", "tp/cli-test"])
    # Run main() — it should print a JSON line and not raise
    pr_state.main()
    out = capsys.readouterr().out
    parsed = json.loads(out.strip())
    assert parsed["state"] == "OPEN"
