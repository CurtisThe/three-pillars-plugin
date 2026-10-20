"""test_delete_fence_projecttop.py — the run kind and primary root follow the project top level
(design delete-fence-own-tree 2.4).

A subagent's cwd can be a linked, detached worktree *inside* the run's own tree
(`repo-wt/a/.tp-scratch/w1`). The run kind and the primary root must come from
the project top level (`CLAUDE_PROJECT_DIR`), not from that cwd: asking git
about the detached worktree answers "seat", which would let a design run delete
a sibling design's tree. Real git throughout (the default git seam), fixtures
under tmp_path; every payload goes through `delete_fence_hook.run` and nothing
is executed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures"))
from delete_fence_repo import build  # noqa: E402

import delete_fence_hook as hook  # noqa: E402


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    """The fixture repo plus a detached linked worktree `w1` nested in `repo-wt/a`."""
    built = build(tmp_path_factory.mktemp("fence-projecttop"))
    paths = dict((k, os.path.realpath(v)) for k, v in built.items())
    w1 = os.path.join(paths["a"], ".tp-scratch", "w1")
    subprocess.run(["git", "-C", paths["a"], "worktree", "add", "-q", "--detach", w1],
                   check=True, capture_output=True, text=True)
    paths["w1"] = os.path.realpath(w1)
    return paths


def _env(repo, project, extra):
    outside = os.path.dirname(repo["repo"])
    env = dict(CLAUDE_PROJECT_DIR=repo[project], HOME=outside, TMPDIR=outside,
               TP_FENCE_PAD_BASE=os.path.join(outside, "no-such-pad"))
    env.update(extra)
    return env


def _denied(repo, command, cwd, project="a", extra=()):
    payload = dict(tool_name="Bash", tool_input=dict(command=command),
                   cwd=repo[cwd], session_id="sess-1")
    out, code = hook.run(payload, env=_env(repo, project, dict(extra)))
    assert code == 0
    return bool(out) and json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


RUNS = [pytest.param((), id="consumer"), pytest.param((("TP_DESIGN_RUN", "1"),), id="design-run")]


@pytest.mark.parametrize("extra", RUNS)
class TestDetachedWorktreeInsideTheRun:
    """Cases A and B: cwd is `repo-wt/a/.tp-scratch/w1`, the project is `repo-wt/a`."""

    def test_a_sibling_design_is_denied(self, repo, extra):
        assert _denied(repo, "rm -rf %s/x" % repo["b"], "w1", extra=extra)

    def test_the_projects_own_tree_is_allowed(self, repo, extra):
        assert not _denied(repo, "rm -rf %s/build/x" % repo["a"], "w1", extra=extra)

    def test_the_detached_worktree_itself_is_allowed(self, repo, extra):
        assert not _denied(repo, "rm -rf %s/y" % repo["w1"], "w1", extra=extra)


class TestSeat:
    """Case C: the seat's project is the main checkout, with no design-run marker."""

    def test_worktree_remove_of_a_design_is_allowed(self, repo):
        assert not _denied(repo, "git worktree remove %s" % repo["b"], "repo", project="repo")

    def test_a_path_inside_a_registered_worktree_is_allowed(self, repo):
        assert not _denied(repo, "rm -rf %s/x" % repo["b"], "repo", project="repo")

    def test_a_path_outside_every_worktree_is_denied(self, repo):
        assert _denied(repo, "rm -rf ~/other", "repo", project="repo")
