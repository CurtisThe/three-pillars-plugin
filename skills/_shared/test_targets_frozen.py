"""test_targets_frozen.py — every commit shape of stages §Part C1 gets its verdict.

design: fragile-test-prevention (Part C1, phase 4)

Real tmp repos via ``attempt_fixture`` (M23): the ambient repository is never read.
Oracle: ``example`` — each shape of ``git rev-list --reverse base..HEAD`` is built as
a concrete repo and asserted against the ``check_pair`` contract from the detailed
design: ``(red_sha|None, reason)``, empty reason = pass, the first sorted offender named.
"""
from __future__ import annotations

from pathlib import Path

import targets_frozen
from attempt_fixture import commit, commit_pair, git, make_seat

TARGETS = "skills/_shared/test_demo.py"
IMPL = "skills/impl/a.py"
OTHER = "skills/impl/b.py"


def row(*test_paths: str) -> dict:
    """An eligibility row whose **Targets** are exactly ``test_paths`` — the set
    ``check_pair`` freezes, read through ``task_scope.row_test_paths``."""
    return {"task_id": "4.1", "files": [], "unparsed_files": [],
            "test": {"files": list(test_paths)}, "test_paths": list(test_paths)}


def test_zero_commits_passes_with_no_red(tmp_path):
    _seat, wt = make_seat(tmp_path)
    base = git(wt, "rev-parse", "HEAD")  # the attempt's base: no commits of its own
    (red, reason) = targets_frozen.check_pair(wt, base, row(TARGETS))
    assert (red, reason) == (None, "")


def test_one_targets_only_commit_passes_with_red_set(tmp_path):
    _seat, wt = make_seat(tmp_path)
    base = git(wt, "rev-parse", "HEAD")
    sha = commit(wt, {TARGETS: "def test_one():\n    assert 1\n"})
    (red, reason) = targets_frozen.check_pair(wt, base, row(TARGETS))
    assert (red, reason) == (sha, "")


def test_one_non_targets_commit_passes_with_no_red(tmp_path):
    _seat, wt = make_seat(tmp_path)
    base = git(wt, "rev-parse", "HEAD")
    sha = commit(wt, {IMPL: "A = 1\n"})
    (red, reason) = targets_frozen.check_pair(wt, base, row(TARGETS))
    assert (red, reason) == (None, "")


def test_one_mixed_commit_fails_naming_first_sorted_target(tmp_path):
    _seat, wt = make_seat(tmp_path)
    base = git(wt, "rev-parse", "HEAD")
    commit(wt, {IMPL: "A = 1\n", TARGETS: "def test_one():\n    assert 1\n"})
    (red, reason) = targets_frozen.check_pair(wt, base, row(TARGETS))
    assert red is None
    assert reason == f"targets changed without a red commit: {TARGETS}"


def test_one_mixed_commit_names_first_sorted_among_several(tmp_path):
    _seat, wt = make_seat(tmp_path)
    base = git(wt, "rev-parse", "HEAD")
    first, second = "skills/a/test_first.py", "skills/z/test_last.py"
    commit(wt, {IMPL: "A = 1\n", first: "def t():\n    assert 1\n",
                second: "def t():\n    assert 2\n"})
    (red, reason) = targets_frozen.check_pair(wt, base, row(first, second))
    assert red is None
    assert reason == f"targets changed without a red commit: {first}"


def test_clean_pair_passes_with_red_as_first_commit(tmp_path):
    _seat, wt = make_seat(tmp_path)
    base = git(wt, "rev-parse", "HEAD")
    red_sha, green_sha = commit_pair(wt,
                                     {TARGETS: "def test_one():\n    assert True\n"},
                                     {IMPL: "A = 1\n"})
    (red, reason) = targets_frozen.check_pair(wt, base, row(TARGETS))
    assert (red, reason) == (red_sha, "")
    assert green_sha != red_sha


def test_red_touching_implementation_file_fails(tmp_path):
    _seat, wt = make_seat(tmp_path)
    base = git(wt, "rev-parse", "HEAD")
    commit_pair(wt,
                {IMPL: "A = 1\n", TARGETS: "def test_one():\n    assert True\n"},
                {OTHER: "B = 2\n"})
    (red, reason) = targets_frozen.check_pair(wt, base, row(TARGETS))
    assert red is None
    assert reason == f"red commit touches non-Targets file: {IMPL}"


def test_green_editing_targets_fails_naming_file(tmp_path):
    """Behavior 1: red, then a green that edits a Targets file — FAIL, the file named."""
    _seat, wt = make_seat(tmp_path)
    base = git(wt, "rev-parse", "HEAD")
    commit_pair(wt, {TARGETS: "def test_one():\n    assert True\n"},
                {IMPL: "A = 1\n", TARGETS: "def test_one():\n    assert False\n"})
    (red, reason) = targets_frozen.check_pair(wt, base, row(TARGETS))
    assert red is None
    assert reason == f"targets edited after red: {TARGETS}"


def test_green_editing_targets_names_first_sorted(tmp_path):
    _seat, wt = make_seat(tmp_path)
    base = git(wt, "rev-parse", "HEAD")
    first, second = "skills/a/test_first.py", "skills/z/test_last.py"
    commit_pair(wt, {first: "def t():\n    assert True\n"},
                {IMPL: "A = 1\n", first: "def t():\n    assert 1\n",
                 second: "def t():\n    assert 2\n"})
    (red, reason) = targets_frozen.check_pair(wt, base, row(first, second))
    assert red is None
    assert reason == f"targets edited after red: {first}"


def test_three_commits_fails_with_count(tmp_path):
    _seat, wt = make_seat(tmp_path)
    base = git(wt, "rev-parse", "HEAD")
    commit_pair(wt, {TARGETS: "def test_one():\n    assert True\n"}, {IMPL: "A = 1\n"})
    commit(wt, {OTHER: "B = 2\n"})
    (red, reason) = targets_frozen.check_pair(wt, base, row(TARGETS))
    assert red is None
    assert reason == "3 commits"
