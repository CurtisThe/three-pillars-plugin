"""test_changed_tests_runs_worktree.py — `record` runs at `head` in its own temp clone
(design: fragile-test-prevention, detailed-design-stages.md Part C4).

Oracle: ``example``. The caller's checkout is often not at the PR head: at ``two-stable`` the
local log-flush commit leaves the design worktree one unpushed commit ahead of it, and a
tracked edit may be in flight. `record` therefore never runs there. These cases build a real tmp
git repo and check that the record binds the PR head whatever the caller's checkout holds, that
the temp clone is gone afterwards (on a pass and on a runner failure), that the changed tests
never see the caller's live worktrees, and that a head that cannot be checked out writes nothing.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

import changed_tests_runs as ctr
import task_scope
from test_changed_tests_runs import OK_TEST, RED_TEST, commit, git, make_repo, runs_file


def worktrees(repo):
    return [line for line in git(repo, "worktree", "list", "--porcelain").splitlines()
            if line.startswith("worktree ")]


@pytest.fixture
def scratch_dirs(monkeypatch):
    """The temp dirs `record` makes for its worktrees, to check they are removed."""
    made = []
    real = tempfile.mkdtemp

    def spy(*args, **kwargs):
        path = real(*args, **kwargs)
        if kwargs.get("prefix") == ctr.TMP_PREFIX:
            made.append(path)
        return path

    monkeypatch.setattr(tempfile, "mkdtemp", spy)
    return made


def test_a_caller_one_commit_ahead_records_the_pr_head(tmp_path):
    repo, base = make_repo(tmp_path)
    pr_head = commit(repo, {"test_ok.py": OK_TEST})
    ahead = commit(repo, {"test_ok.py": RED_TEST}, "log flush")  # the caller's own HEAD
    assert ctr.read(repo, pr_head) is None  # no prior record
    out = ctr.record(repo, base, pr_head)
    assert out["head"] == pr_head
    assert out["verdict"] == "pass"  # the ahead commit's red test was never run
    assert ctr.read(repo, pr_head)["head"] == pr_head
    assert ctr.read(repo, ahead) is None


def test_a_caller_ahead_with_a_green_test_cannot_pass_a_red_head(tmp_path):
    repo, base = make_repo(tmp_path)
    pr_head = commit(repo, {"test_red.py": RED_TEST})
    commit(repo, {"test_red.py": OK_TEST}, "log flush")
    assert ctr.record(repo, base, pr_head)["verdict"] == "fail"


@pytest.mark.parametrize("committed, edited, expected", [
    (OK_TEST, RED_TEST, "pass"),
    (RED_TEST, OK_TEST, "fail"),
])
def test_a_tracked_edit_in_the_callers_checkout_never_changes_the_verdict(
        tmp_path, committed, edited, expected):
    repo, base = make_repo(tmp_path)
    head = commit(repo, {"test_subject.py": committed})
    (repo / "test_subject.py").write_text(edited, encoding="utf-8")
    assert ctr.record(repo, base, head)["verdict"] == expected
    assert (repo / "test_subject.py").read_text(encoding="utf-8") == edited
    assert git(repo, "status", "--porcelain") == "M test_subject.py"  # nothing else was left


def test_the_tests_never_run_in_the_callers_checkout(tmp_path):
    repo, base = make_repo(tmp_path)
    head = commit(repo, {"test_ok.py": OK_TEST})
    ctr.record(repo, base, head)
    assert not (repo / ".pytest_cache").exists()
    assert not (repo / "__pycache__").exists()


def test_the_temp_worktree_is_gone_after_a_pass(tmp_path, scratch_dirs):
    repo, base = make_repo(tmp_path)
    head = commit(repo, {"test_ok.py": OK_TEST})
    assert ctr.record(repo, base, head)["verdict"] == "pass"
    assert len(scratch_dirs) == 1
    assert not os.path.exists(scratch_dirs[0])
    assert worktrees(repo) == [f"worktree {repo.resolve()}"]


def test_the_temp_worktree_is_gone_after_a_runner_that_cannot_start(
        tmp_path, scratch_dirs, monkeypatch):
    repo, base = make_repo(tmp_path)
    head = commit(repo, {"test_ok.py": OK_TEST})
    monkeypatch.setattr(task_scope, "resolve_runner",
                        lambda root, override: ("no-such-runner-binary -q", "override"))
    out = ctr.record(repo, base, head)
    assert out["verdict"] == "unverified"
    assert not os.path.exists(scratch_dirs[0])
    assert len(worktrees(repo)) == 1


def test_the_temp_worktree_is_gone_when_the_runner_raises(tmp_path, scratch_dirs, monkeypatch):
    repo, base = make_repo(tmp_path)
    head = commit(repo, {"test_ok.py": OK_TEST})

    def boom(*args, **kwargs):
        raise RuntimeError("kaput")

    monkeypatch.setattr(ctr.junit_verdict, "run_judged", boom)
    with pytest.raises(RuntimeError):
        ctr.record(repo, base, head)
    assert not os.path.exists(scratch_dirs[0])
    assert len(worktrees(repo)) == 1
    assert not runs_file(repo).exists()


def test_an_unknown_head_writes_nothing_and_says_why(tmp_path, scratch_dirs):
    repo, base = make_repo(tmp_path)
    out = ctr.record(repo, base, "f" * 40)
    assert out["written"] is False
    assert out["reason"].startswith(ctr.HEAD_UNAVAILABLE)
    assert not runs_file(repo).exists()
    assert ctr.read(repo, "f" * 40) is None
    assert scratch_dirs == []  # refused before any worktree was made


def test_an_unknown_head_leaves_the_existing_record_alone(tmp_path):
    repo, base = make_repo(tmp_path)
    head = commit(repo, {"test_ok.py": OK_TEST})
    kept = ctr.record(repo, base, head)
    out = ctr.record(repo, base, "f" * 40)
    assert out["written"] is False
    assert ctr.read(repo, head) == {k: v for k, v in kept.items() if k != "written"}


def test_an_unknown_base_writes_nothing_and_says_why(tmp_path):
    repo, _base = make_repo(tmp_path)
    head = commit(repo, {"test_ok.py": OK_TEST})
    out = ctr.record(repo, "f" * 40, head)
    assert out["written"] is False
    assert out["reason"].startswith(ctr.BASE_UNAVAILABLE)
    assert not Path(runs_file(repo)).exists()


# A changed test that, like test_shipped_currency_check running framework-check.sh (inv 32),
# reads `git worktree list` from its cwd: the run's checkout must have no sibling worktrees.
LISTS_ONLY_ITSELF = (
    "import subprocess\n"
    "def test_only_this_checkout():\n"
    "    out = subprocess.run(['git', 'worktree', 'list', '--porcelain'], capture_output=True,\n"
    "                         text=True, check=True).stdout\n"
    "    assert out.count('worktree ') == 1\n"
)


def test_the_run_never_sees_the_callers_live_worktrees(tmp_path):
    repo, base = make_repo(tmp_path)
    head = commit(repo, {"test_isolated.py": LISTS_ONLY_ITSELF})
    git(repo, "worktree", "add", "-q", "-b", "tp/other", str(tmp_path / "other"))
    out = ctr.record(repo, base, head)
    assert (out["verdict"], out["reason"]) == ("pass", "")
    assert len(worktrees(repo)) == 2  # the caller's own registrations are untouched
