"""Tests for `label_manager.ensure_pr_label`.

Three scenarios exercise the idempotent label-ensure dance:

1. First call on a PR without the label: `gh pr view` reports no labels,
   `gh pr edit --add-label` succeeds -> two calls.
2. Second call after the label is already present: `gh pr view` reports
   the label -> one call only, no edit.
3. Label does not yet exist on the repo: `gh pr view` reports no labels,
   `gh pr edit --add-label` fails with "not found" stderr, `gh label
   create` succeeds, retry `gh pr edit --add-label` succeeds -> four calls.

All tests stub `label_manager.subprocess.run` (the module-local binding)
so we never shell out to the real `gh`.

Run with: pytest skills/tp-pr-fix/scripts/test_label_manager.py -q
"""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest


PR_URL = "https://github.com/example/repo/pull/42"
LABEL = "tp:do-not-merge-yet"


def _ok(stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def _fail(stderr: str, stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=1, stdout=stdout, stderr=stderr)


def _cmd(call) -> list[str]:
    """Extract the argv list from a recorded mock call."""
    args, _kwargs = call
    return list(args[0])


def test_first_call_creates_label_and_adds():
    from label_manager import ensure_pr_label

    side_effects = [
        _ok(stdout=json.dumps({"labels": []})),  # pr view
        _ok(),  # pr edit --add-label
    ]

    with patch("label_manager.subprocess.run", side_effect=side_effects) as run:
        ensure_pr_label(PR_URL, LABEL)

    assert run.call_count == 2, f"expected 2 calls, got {run.call_count}"

    first = _cmd(run.call_args_list[0])
    assert first[:3] == ["gh", "pr", "view"]
    assert PR_URL in first
    assert "--json" in first and "labels" in first

    second = _cmd(run.call_args_list[1])
    assert second[:3] == ["gh", "pr", "edit"]
    assert PR_URL in second
    assert "--add-label" in second
    assert LABEL in second


def test_second_call_is_noop():
    from label_manager import ensure_pr_label

    side_effects = [
        _ok(stdout=json.dumps({"labels": [{"name": LABEL}]})),  # pr view
    ]

    with patch("label_manager.subprocess.run", side_effect=side_effects) as run:
        ensure_pr_label(PR_URL, LABEL)

    assert run.call_count == 1, f"expected 1 call, got {run.call_count}"

    only = _cmd(run.call_args_list[0])
    assert only[:3] == ["gh", "pr", "view"]


def test_creates_missing_label_via_gh_label_create():
    from label_manager import ensure_pr_label

    side_effects = [
        _ok(stdout=json.dumps({"labels": []})),  # pr view
        _fail(stderr="could not find label: not found"),  # first pr edit
        _ok(),  # gh label create
        _ok(),  # retry pr edit
    ]

    with patch("label_manager.subprocess.run", side_effect=side_effects) as run:
        ensure_pr_label(PR_URL, LABEL)

    assert run.call_count == 4, f"expected 4 calls, got {run.call_count}"

    first = _cmd(run.call_args_list[0])
    assert first[:3] == ["gh", "pr", "view"]

    second = _cmd(run.call_args_list[1])
    assert second[:3] == ["gh", "pr", "edit"]
    assert "--add-label" in second and LABEL in second

    third = _cmd(run.call_args_list[2])
    assert third[:3] == ["gh", "label", "create"]
    assert LABEL in third

    fourth = _cmd(run.call_args_list[3])
    assert fourth[:3] == ["gh", "pr", "edit"]
    assert "--add-label" in fourth and LABEL in fourth
