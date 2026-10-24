"""A fleet or base-sync window starts before the run dir exists (run-scratch-in-fence fix 1).

The window's env already names TMPDIR=<wt>/.tp-scratch/run, but nothing has provisioned
the dir yet. The fences must still keep the run's own top root (the tree), must still
refuse a create under the shared /tmp, and the window builders must create the dir.
"""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

import run_scratch
from delete_fence_roots import compute_roots
from test_create_fence_hook import TMP, bash, denial, fence, make_env, make_repo

UID = 1000


@pytest.fixture()
def repo(tmp_path):
    r = make_repo(tmp_path)
    shutil.rmtree(r["run"])
    return r


def _git(args, cwd):
    return ""


def test_create_fence_allows_the_tree_and_refuses_tmp_while_the_run_dir_is_absent(repo):
    assert not os.path.exists(repo["run"])
    inside = os.path.join(repo["a"], "three-pillars-docs", "tp-designs", "x", "design.md")
    got = fence(repo, "Write", file_path=inside)
    assert got == ("", 0), "Write inside the tree (tp-designs) must be allowed: %r" % (got,)
    got = bash(repo, "cat >> %s <<X\nhi\nX" % inside)
    assert got == ("", 0), "heredoc append inside the tree (tp-designs) must be allowed: %r" % (got,)
    got = bash(repo, "touch %s/x" % TMP)[0]
    assert denial(got), "touch %s/x under the shared /tmp must be refused, got: " + repr(got)
    got = fence(repo, "Write", file_path=os.path.join(TMP, "x"))[0]
    assert denial(got), "Write of x under the shared /tmp must be refused, got: %r" % (got,)


def test_create_fence_still_refuses_home_while_the_run_dir_is_absent(repo):
    assert denial(bash(repo, "mkdir ~/tmp")[0])


def test_delete_fence_roots_keep_the_top_while_the_run_dir_is_absent(repo):
    top = repo["a"]
    info = {"top": top, "git_dir": top + "/.git", "common_dir": top + "/.git",
            "branch": "tp/a"}
    env = make_env(repo)
    roots = compute_roots("design-run", info, top, env, _git, None, None, UID)
    assert top in roots, roots
    assert os.path.realpath(TMP) not in roots and repo["home"] not in roots
    assert not os.path.exists(repo["run"])


def test_a_foreign_tmpdir_still_drops_the_top(repo):
    top = repo["a"]
    info = {"top": top, "git_dir": top + "/.git", "common_dir": top + "/.git",
            "branch": "tp/a"}
    other = os.path.join(os.path.dirname(top), "elsewhere", ".tp-scratch", "run")
    roots = compute_roots("design-run", info, top, make_env(repo, TMPDIR=other),
                          _git, None, None, UID)
    assert top in roots, "an unrelated TMPDIR keeps the top: %s" % (roots,)
    # a run dir that is another tree's, nested inside the top, is not the run's own
    nested = os.path.join(top, "nested", ".tp-scratch", "run")
    inner = os.path.join(top, "sub")
    for foreign in (nested, inner):
        roots = compute_roots("design-run", info, top, make_env(repo, TMPDIR=foreign),
                              _git, None, None, UID)
        assert top not in roots, "top not in roots expected for TMPDIR=%s: %s" % (foreign, roots)


def _git_wt(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    g = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(g + ["init", "-q", str(repo)], check=True)
    subprocess.run(g + ["-C", str(repo), "commit", "-q", "--allow-empty", "-m", "i"], check=True)
    wt = tmp_path / "wt"
    subprocess.run(g + ["-C", str(repo), "worktree", "add", "-q", "-b", "tp/foo", str(wt)],
                   check=True)
    return str(repo), str(wt)


def test_base_sync_launch_creates_the_run_dir(tmp_path, capsys):
    import launch_design_run
    repo, wt = _git_wt(tmp_path)
    assert not os.path.exists(run_scratch.run_dir(wt))
    rc = launch_design_run.main(["foo", "--base-sync"], env=dict(os.environ), cwd=repo)
    assert rc == 0
    assert os.path.isdir(run_scratch.run_dir(wt))


def test_base_sync_dry_run_creates_nothing(tmp_path, capsys):
    import launch_design_run
    repo, wt = _git_wt(tmp_path)
    rc = launch_design_run.main(["foo", "--base-sync", "--dry-run"], env=dict(os.environ),
                                cwd=repo)
    assert rc == 0
    assert not os.path.exists(run_scratch.run_dir(wt))
