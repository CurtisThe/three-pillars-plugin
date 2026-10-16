"""test_attempt_start_check.py — worker start-of-task sanity check.

design: hybrid-routing-hardening (Task 4.1)

Real tmp repo + `git worktree add -b`; every invocation of the script under
test runs as a subprocess with an explicit env (GIT_DIR/GIT_WORK_TREE/
GIT_INDEX_FILE popped, since a pre-commit hook running this suite may have
set them) so it never reads the ambient repository's git state.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from attempt_fixture import commit, git

SCRIPT = str(Path(__file__).parent / "attempt_start_check.py")
BRANCH = "tp-attempt/demo/1.1"
TASK_ID = "1.1"


def _script_env() -> dict:
    env = os.environ.copy()
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(key, None)
    return env


def _run(cwd, attempt_dir, branch: str, base_sha: str, *, env: dict | None = None,
          task_id: str = TASK_ID) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, SCRIPT, "--task", task_id, "--attempt-dir", str(attempt_dir),
         "--branch", branch, "--base", base_sha],
        cwd=str(cwd), capture_output=True, text=True, env=env or _script_env(),
    )


def _assert_fail(result: subprocess.CompletedProcess, check_name: str) -> dict:
    assert result.returncode == 1
    lines = result.stdout.strip("\n").splitlines()
    assert len(lines) == 1
    assert result.stderr == ""
    data = json.loads(lines[0])
    assert set(data.keys()) == {"task_id", "sha", "claimed", "check", "expected", "actual"}
    assert data["task_id"] == TASK_ID
    assert data["sha"] is None
    assert data["claimed"] == "aborted-cwd"
    assert data["check"] == check_name
    return data


def _base_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    base_sha = commit(repo, {"README.md": "demo\n"}, "base")
    return repo, base_sha


def _worktree(repo: Path, branch: str, path: Path) -> Path:
    git(repo, "worktree", "add", "-q", "-b", branch, str(path))
    return path


def test_match_passes_silently(tmp_path):
    repo, base_sha = _base_repo(tmp_path)
    wt = _worktree(repo, BRANCH, tmp_path / "wt")
    before = git(wt, "status", "--porcelain")

    result = _run(wt, wt, BRANCH, base_sha)

    after = git(wt, "status", "--porcelain")
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    assert before == after


def test_run_from_main_checkout_fails_cwd(tmp_path):
    repo, base_sha = _base_repo(tmp_path)
    wt = _worktree(repo, BRANCH, tmp_path / "wt")

    result = _run(repo, wt, BRANCH, base_sha)

    _assert_fail(result, "cwd")


def test_subdirectory_of_worktree_fails_toplevel(tmp_path):
    repo, base_sha = _base_repo(tmp_path)
    wt = _worktree(repo, BRANCH, tmp_path / "wt")
    sub = wt / "sub"
    sub.mkdir()

    result = _run(sub, sub, BRANCH, base_sha)

    _assert_fail(result, "toplevel")


def test_wrong_branch_fails_branch(tmp_path):
    repo, base_sha = _base_repo(tmp_path)
    wt = _worktree(repo, BRANCH, tmp_path / "wt")
    before = git(wt, "status", "--porcelain")

    result = _run(wt, wt, "some-other-branch", base_sha)

    after = git(wt, "status", "--porcelain")
    _assert_fail(result, "branch")
    assert before == after


def test_detached_head_fails_branch(tmp_path):
    repo, base_sha = _base_repo(tmp_path)
    wt = _worktree(repo, BRANCH, tmp_path / "wt")
    git(wt, "checkout", "--detach", "-q")

    result = _run(wt, wt, BRANCH, base_sha)

    data = _assert_fail(result, "branch")
    assert data["actual"] == "HEAD"


def test_head_past_base_fails_base(tmp_path):
    repo, base_sha = _base_repo(tmp_path)
    wt = _worktree(repo, BRANCH, tmp_path / "wt")
    commit(wt, {"extra.txt": "x\n"}, "extra")

    result = _run(wt, wt, BRANCH, base_sha)

    _assert_fail(result, "base")


def test_non_git_dir_fails_git(tmp_path):
    nongit = tmp_path / "nongit"
    nongit.mkdir()
    env = _script_env()
    env["GIT_CEILING_DIRECTORIES"] = str(tmp_path)

    result = _run(nongit, nongit, BRANCH, "0" * 40, env=env)

    _assert_fail(result, "git")


def test_symlinked_equal_paths_pass(tmp_path):
    repo, base_sha = _base_repo(tmp_path)
    wt = _worktree(repo, BRANCH, tmp_path / "wt")
    link = tmp_path / "link"
    link.symlink_to(wt)

    result = _run(link, link, BRANCH, base_sha)

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
