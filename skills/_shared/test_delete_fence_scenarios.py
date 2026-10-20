"""Scenario tests for the delete fence (design delete-fence-own-tree 1.10).

End to end through `delete_fence_hook.run` with the real git seam on the
`fixtures/delete_fence_repo.py` repo (`repo`, `repo-wt/a`, `repo-wt/b`, all
under pytest's `tmp_path`). Three situations: a design run in `repo-wt/a`, the
seat in the main checkout, and a repo with no tp markers. Every command is only
classified; nothing here runs a delete.

`~` is written out as the fake HOME's absolute path: the classifier treats a
literal `~` operand as unknown (always denied), so the marker scenario names the
same directory without the tilde.
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

SID = "sess-1"
PROJ = "-proj"


def _git(args, cwd):
    subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    base = tmp_path_factory.mktemp("fence-scen")
    paths = {k: os.path.realpath(v) for k, v in build(base / "w").items()}
    agent = os.path.join(paths["repo"], ".claude", "worktrees", "agent-1")
    _git(["worktree", "add", "-q", "--detach", agent], paths["repo"])
    paths["agent"] = os.path.realpath(agent)
    home = base / "home"
    (home / "t" / "foo").mkdir(parents=True)
    (home / "other-repo").mkdir()
    pad = base / "claude-1000"
    for sid in (SID, "sess-2"):
        (pad / PROJ / sid / "x").mkdir(parents=True)
    tmpdir = base / "tmpdir"
    tmpdir.mkdir()
    proj = base / "projects" / "p"
    (proj / SID / "subagents").mkdir(parents=True)
    paths.update(home=os.path.realpath(home), pad=os.path.realpath(pad),
                 tmpdir=os.path.realpath(tmpdir), proj=str(proj))
    return paths


def _env(world, run=True, **extra):
    env = {"HOME": world["home"], "TMPDIR": world["tmpdir"],
           "TP_FENCE_PAD_BASE": world["pad"]}
    if run:
        env.update(TP_DESIGN_RUN="1", CLAUDE_PROJECT_DIR=world["a"])
    env.update(extra)
    return env


def _payload(command, cwd, **extra):
    p = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd,
         "session_id": SID, "transcript_path": "/nonexistent/projects/p/s.jsonl"}
    p.update(extra)
    return p


def _denied(out):
    return bool(out) and json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


def _run_out(world, command, cwd=None, env=None, **extra):
    out, code = hook.run(_payload(command, cwd or world["a"], **extra),
                         env=_env(world) if env is None else env)
    assert code == 0
    return out


# --- design run in repo-wt/a -------------------------------------------------

@pytest.mark.parametrize("command", [
    "rm -rf {a}/x",
    "rm -rf {a}/.tp-scratch/x",
    "git worktree remove {a}/.tp-scratch/w1",
    "git clean -fdx",
])
def test_design_run_may_delete_inside_its_own_tree(world, command):
    assert _run_out(world, command.format(**world)) == ""


def test_design_run_may_not_delete_a_sibling_design(world):
    # A sibling design's worktree is never a root, from either pole. The
    # relative pole must be the *real* path from the run's cwd: from
    # `repo-wt/a` the sibling is `../b`, while `../repo-wt/b` names a
    # directory that does not exist (`repo-wt/repo-wt/b`).
    assert _denied(_run_out(world, "rm -rf ../repo-wt/b"))
    assert _denied(_run_out(world, "rm -rf %s" % world["b"]))
    rel = os.path.relpath(world["b"], world["a"])
    assert _denied(_run_out(world, "rm -rf %s" % rel))
    # The sibling may not become a root either: a root set that nests it still
    # refuses, because its own contents are denied.
    assert _denied(_run_out(world, "rm -rf %s/.git" % world["b"]))
    assert _denied(_run_out(world, "rm -rf %s/x" % world["b"]))


def _marker_extra(world, marker):
    """Payload fields pointing at a subagent transcript whose first user turn
    carries `TP_SCRATCH: <marker>` (the reviewer hook's marker shape)."""
    sub = os.path.join(world["proj"], SID, "subagents", "agent-a1.jsonl")
    with open(sub, "w") as fh:
        fh.write(json.dumps({"type": "user", "message": {
            "content": "TP_SCRATCH: %s\n\ngo" % marker}}) + "\n")
    return {"transcript_path": os.path.join(world["proj"], SID + ".jsonl"),
            "agent_id": "a1", "agent_type": "general-purpose"}


def test_design_run_home_scratch_needs_a_marker(world):
    foo = os.path.join(world["home"], "t", "foo")
    assert _denied(_run_out(world, "rm -rf ~/t/foo"))
    assert _denied(_run_out(world, "rm -rf %s/out" % foo))
    extra = _marker_extra(world, foo)
    # A path is allowed only when strictly inside a root (design Behaviors 1).
    assert _run_out(world, "rm -rf %s/out" % foo, **extra) == ""
    assert _denied(_run_out(world, "rm -rf %s/../bar" % foo, **extra))


def test_design_run_marker_naming_a_shared_root_is_not_a_root(world):
    extra = _marker_extra(world, os.path.dirname(world["home"]))
    assert _denied(_run_out(world, "rm -rf %s" % os.path.join(world["home"], "other-repo"),
                            **extra))


def test_subagent_worktree_under_the_main_checkout_is_its_own_root(world):
    agent = world["agent"]
    assert _run_out(world, "rm -rf %s/x" % agent, cwd=agent) == ""
    assert _run_out(world, "rm -rf x", cwd=agent) == ""


# --- the seat (main checkout, no TP_DESIGN_RUN) -----------------------------

def _seat(world, command):
    return _run_out(world, command, cwd=world["repo"], env=_env(world, run=False))


@pytest.mark.parametrize("command", [
    "git worktree remove ../repo-wt/b",
    "git branch -D tp/b",
    "cd build && rm -rf out",
])
def test_seat_allows_teardown_and_in_repo_deletes(world, command):
    assert _seat(world, command) == ""


def test_seat_may_not_delete_another_repo(world):
    assert _denied(_seat(world, "rm -rf ~/other-repo"))
    assert _denied(_seat(world, "rm -rf %s" % os.path.join(world["home"], "other-repo")))


# --- harness scratchpad ----------------------------------------------------

def test_harness_pad_of_this_session_only(world):
    own = os.path.join(world["pad"], PROJ, SID, "x")
    other = os.path.join(world["pad"], PROJ, "sess-2", "x")
    assert _run_out(world, "rm -rf %s" % own) == ""
    assert _denied(_run_out(world, "rm -rf %s" % other))
    assert _seat(world, "rm -rf %s" % own) == ""
    assert _denied(_seat(world, "rm -rf %s" % other))


# --- non-tp repos and the off switch ----------------------------------------

def _plain_repo(tmp_path, commit):
    repo = tmp_path / "plain"
    repo.mkdir()
    _git(["init", "-q", "-b", "master"], repo)
    if commit:
        (repo / "f").write_text("x\n")
        _git(["add", "f"], repo)
        _git(["-c", "user.email=f@example.invalid", "-c", "user.name=F",
              "commit", "-q", "-m", "init"], repo)
    return str(repo)


@pytest.mark.parametrize("commit", [True, False], ids=["with-commit", "no-commit"])
def test_non_tp_repo_is_allowed_silently(world, tmp_path, commit):
    repo = _plain_repo(tmp_path, commit)
    env = _env(world, run=False)
    assert _run_out(world, "rm -rf /home/elsewhere", cwd=repo, env=env) == ""


def test_directory_outside_any_repo_is_allowed_silently(world, tmp_path, monkeypatch):
    bare = tmp_path / "nogit"
    bare.mkdir()
    # The hook's git seam reads the process env; stop git's upward search here.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    env = _env(world, run=False)
    assert _run_out(world, "rm -rf /home/elsewhere", cwd=str(bare), env=env) == ""


def test_fence_off_switch_allows(world):
    env = _env(world, TP_DELETE_FENCE="off")
    assert _run_out(world, "rm -rf %s" % world["b"], env=env) == ""
