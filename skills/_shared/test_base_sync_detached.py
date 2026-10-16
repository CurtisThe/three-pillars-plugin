"""build_scenario from a detached-HEAD source checkout (a CI pull-request checkout, a
certify pole): the fixture clones the source's HEAD commit with `--shared` and names it
`base_ref` in origin_dir, instead of failing on `git symbolic-ref HEAD`."""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))

import base_sync_repo  # noqa: E402
from base_sync_repo import build_scenario  # noqa: E402
from test_base_sync_footprint import MIB, _tree_bytes, clean_git_env  # noqa: E402


def _git(cwd, *args) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                          check=True, env=clean_git_env()).stdout.strip()


def _dir(path):
    path.mkdir()
    return path


def _detached_source(tmp_path, *, keep_branches: bool):
    """A `--shared`, no-checkout clone of the framework checkout with HEAD detached at its
    HEAD commit: the source shape a detached checkout presents to build_scenario. With
    keep_branches the sha is also a local branch tip (a certify pole); without, no local
    branch holds it (a CI pull-request merge checkout)."""
    live = base_sync_repo._this_repo_root()
    sha = _git(live, "rev-parse", "HEAD")
    tmp_path.mkdir()
    src = tmp_path / "src"
    subprocess.run(["git", "clone", "--quiet", "--shared", "--no-checkout", str(live), str(src)],
                   capture_output=True, text=True, check=True, env=clean_git_env())
    _git(src, "update-ref", "--no-deref", "HEAD", sha)
    if not keep_branches:
        for head in _git(src, "for-each-ref", "--format=%(refname)", "refs/heads").split():
            _git(src, "update-ref", "-d", head)
    return src, sha


@pytest.mark.parametrize("keep_branches", [True, False], ids=["sha-at-branch-tip", "sha-on-no-branch"])
def test_build_scenario_succeeds_from_a_detached_source(tmp_path, monkeypatch, keep_branches):
    src, sha = _detached_source(tmp_path / "s", keep_branches=keep_branches)
    probe = subprocess.run(["git", "-C", str(src), "symbolic-ref", "-q", "HEAD"],
                           capture_output=True, text=True, env=clean_git_env())
    assert probe.returncode == 1, "the source must present a detached HEAD"
    monkeypatch.setattr(base_sync_repo, "_this_repo_root", lambda: src)
    s = build_scenario(_dir(tmp_path / "t"), base_ref="main", design_branch="design")
    assert _git(s.origin_dir, "symbolic-ref", "--short", "HEAD") == "main"
    assert _git(s.origin_dir, "rev-parse", "main~2") == sha, "base_ref = source HEAD + 2 seeds"
    assert _git(s.origin_dir, "for-each-ref", "--format=%(refname:short)", "refs/heads") == "main"
    assert _git(s.repo_dir, "symbolic-ref", "--short", "HEAD") == "design"
    assert s.head("design") == s.origin_head()
    assert (s.origin_dir / ".git" / "objects" / "info" / "alternates").is_file()
    for d in (s.origin_dir, s.repo_dir):
        assert _tree_bytes(d / ".git" / "objects") <= 2 * MIB


def test_detached_source_with_another_base_ref(tmp_path, monkeypatch):
    src, sha = _detached_source(tmp_path / "s", keep_branches=False)
    monkeypatch.setattr(base_sync_repo, "_this_repo_root", lambda: src)
    s = build_scenario(_dir(tmp_path / "t"), base_ref="master", design_branch="tp/x")
    assert _git(s.origin_dir, "for-each-ref", "--format=%(refname:short)", "refs/heads") == "master"
    assert _git(s.origin_dir, "merge-base", "--is-ancestor", sha, "master") == ""
    assert _git(s.repo_dir, "symbolic-ref", "--short", "HEAD") == "tp/x"
