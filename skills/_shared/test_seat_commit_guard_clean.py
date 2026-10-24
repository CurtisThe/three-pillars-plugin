"""test_seat_commit_guard_clean.py — a merge with no conflict left to decide passes the guard.

design: seat-escalate-first Phase 3 check C1. `/tp-merge-from-main` runs `git merge
--no-commit --no-ff`, so `MERGE_HEAD` exists even when git merged cleanly; that commit has
nothing to escalate. A conflict the seat resolved by hand still refuses (merge-tree exits
1 on it), and any git error or an old git keeps the refusal. Fixtures reuse
`test_seat_commit_guard`'s helpers; explicit env mappings, no network.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import seat_commit_guard as guard  # noqa: E402
import seat_scope  # noqa: E402
from test_seat_commit_guard import CLAUDE, SEAT, _git, _merge_head, _setup  # noqa: E402


def _clean_merge(tmp_path):
    """A run worktree mid-merge of a branch that touches a different file (no conflict)."""
    base, wt = _setup(tmp_path, merge=False)
    _git(base, "checkout", "-q", "-b", "clean", "main")
    (base / "other.txt").write_text("added\n", encoding="utf-8")
    _git(base, "add", "other.txt")
    _git(base, "commit", "-q", "-m", "clean")
    _git(base, "checkout", "-q", "main")
    _git(wt, "merge", "-q", "--no-commit", "--no-ff", "clean")
    assert _merge_head(wt).exists(), "fixture: --no-commit leaves MERGE_HEAD"
    assert not _git(wt, "ls-files", "-u").stdout.strip(), "fixture: the merge is clean"
    return wt


@pytest.mark.parametrize("env", [SEAT, CLAUDE], ids=["seat-role", "claude-code"])
def test_a_clean_no_conflict_merge_passes(tmp_path, env):
    assert guard.check(_clean_merge(tmp_path), env) is None


def test_main_allows_a_clean_merge(tmp_path):
    wt = _clean_merge(tmp_path)
    assert guard.main(["--repo", str(wt)], env=SEAT) == 0


def test_a_hand_resolved_conflict_still_refuses(tmp_path):
    _, wt = _setup(tmp_path)  # a real conflict
    (wt / "conflict.txt").write_text("resolved by the seat\n", encoding="utf-8")
    _git(wt, "add", "conflict.txt")
    assert not _git(wt, "ls-files", "-u").stdout.strip(), "fixture: no unmerged paths left"
    assert guard.check(wt, SEAT) is not None


def test_an_unresolved_conflict_still_refuses(tmp_path):
    _, wt = _setup(tmp_path)
    assert guard.check(wt, CLAUDE) is not None


def test_extra_staged_changes_on_a_clean_merge_refuse(tmp_path):
    wt = _clean_merge(tmp_path)
    (wt / "smuggled.txt").write_text("not part of the merge\n", encoding="utf-8")
    _git(wt, "add", "smuggled.txt")
    assert guard.check(wt, SEAT) is not None


def test_a_merge_tree_error_refuses(tmp_path, monkeypatch):
    wt = _clean_merge(tmp_path)
    real = seat_scope._default_run_git

    def broken(args, cwd):
        return (129, "") if args[:1] == ["merge-tree"] else real(args, cwd)

    monkeypatch.setattr(seat_scope, "_default_run_git", broken)
    assert guard.check(wt, SEAT) is not None  # git < 2.38: fail closed


def test_the_run_and_the_operator_still_pass_a_clean_merge(tmp_path):
    wt = _clean_merge(tmp_path)
    assert guard.check(wt, {"CLAUDE_LAUNCHER_ROLE": "seat", "TP_DESIGN_RUN": "1"}) is None
    assert guard.check(wt, {}) is None
