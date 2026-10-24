"""Tests for owned_agent_branches.py — per-slug ownership record."""

from __future__ import annotations

import pytest

from owned_agent_branches import branch_for_worktree, main, owned, record

WT = "/r/.claude/worktrees/agent-ad74d3efd33338a64"
BR = "worktree-agent-ad74d3efd33338a64"


def test_branch_for_worktree():
    assert branch_for_worktree(WT) == BR


@pytest.mark.parametrize(
    "path", ["/r/main", "/r/agent-", "/r/agent-../x", "", "/r/agent-a_b"]
)
def test_branch_for_bad_path(path):
    assert branch_for_worktree(path) is None


def test_record_and_owned(tmp_path):
    root = str(tmp_path)
    assert record(root, "run-a", WT) is True
    assert record(root, "run-a", WT) is True
    assert owned(root, "run-a") == {BR}
    assert owned(root, "run-b") == set()


def test_record_twice_keeps_one_entry(tmp_path):
    root = str(tmp_path)
    record(root, "run-a", WT)
    record(root, "run-a", WT)
    assert len(owned(root, "run-a")) == 1


def test_missing_file_is_empty(tmp_path):
    assert owned(str(tmp_path), "nope") == set()


def test_bad_slug_or_path_writes_nothing(tmp_path):
    root = str(tmp_path)
    assert record(root, "../x", WT) is False
    assert record(root, "run-a", "/r/main") is False
    assert not (tmp_path / ".tp-scratch").exists()


def test_extra_text_line_dropped(tmp_path):
    d = tmp_path / ".tp-scratch" / "owned-agent-branches"
    d.mkdir(parents=True)
    (d / "run-a.txt").write_text(BR + " junk\n" + BR + "\n", encoding="utf-8")
    assert owned(str(tmp_path), "run-a") == {BR}


def test_cli_record(tmp_path):
    root = str(tmp_path)
    rc = main(["record", "--slug", "run-a", "--worktree", WT, "--root", root])
    assert rc == 0
    assert owned(root, "run-a") == {BR}


def test_cli_bad_argument_fails_open():
    assert main(["record", "--bogus"]) == 0
