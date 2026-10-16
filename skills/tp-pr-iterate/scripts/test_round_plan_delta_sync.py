"""round_plan.delta_text across a base sync — the delta is the fix, never the base.

design: review-convergence (Task 4.2, detailed-design-pr-loop §D3)

Review bar: a delta round reviews what the loop changed. A mid-loop sync of the PR
base brings base commits into the PR's first-parent line; their hunks must NOT join
the delta, so the security lens (fed from `delta_text`, not
`trust_boundary.surfaces_for_range`) stays off for a `subprocess.run` a base author
added. Only a sync merge's own hand-resolution hunks (`git show --remerge-diff`)
count, because those were written by the loop.
Oracle: example — exact lines on a real tmp git repo (test-fragility).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import round_plan  # noqa: E402
import trust_boundary  # noqa: E402

_GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
            "GIT_CONFIG_NOSYSTEM": "1", "HOME": "/nonexistent"}

BASE_WORK = ("import subprocess\n"
             "\n"
             "\n"
             "def go(argv):\n"
             "    subprocess.run(argv)\n")


def _git(repo, *args):
    env = {**os.environ, **_GIT_ENV}
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                         text=True, env=env, check=True)
    return out.stdout.strip()


def _write(repo, rel, text):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _commit(repo, message):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _init(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.name", "t")
    _git(r, "config", "user.email", "t@t")
    _write(r, "base_only.py", "one = 1\n")
    _write(r, "fix.py", "total = 1 + 1\n")
    _commit(r, "base")
    return r


def _base_moves(r):
    """`main` moves on: a base commit that adds a subprocess call site."""
    _git(r, "checkout", "-q", "main")
    _write(r, "base_only.py", "one = 1\n" + BASE_WORK)
    return _commit(r, "base work adds a call site")


@pytest.fixture()
def synced(tmp_path):
    """pr: round-1 head `A` → clean sync merge of `main` → one fix commit = head."""
    r = _init(tmp_path)
    _git(r, "checkout", "-q", "-b", "pr")
    _write(r, "fix.py", "total = 1 + 1\nfixed = True\n")
    a = _commit(r, "A pr commit")
    base_commit = _base_moves(r)
    _git(r, "checkout", "-q", "pr")
    _git(r, "merge", "--no-ff", "-q", "-m", "sync main", "main")
    merge = _git(r, "rev-parse", "HEAD")
    _write(r, "fix.py", "total = 1 + 1\nfixed = True\nw = 3\n")
    fix = _commit(r, "fix round 2")
    return {"repo": r, "prior": a, "base_commit": base_commit, "merge": merge,
            "fix": fix, "head": fix}


@pytest.fixture()
def conflicted(synced):
    """The same PR, then a second sync that conflicts and the loop resolves it."""
    r, prior = synced["repo"], synced["head"]
    _git(r, "checkout", "-q", "main")
    _write(r, "fix.py", "total = 9\n")
    _commit(r, "base work conflicts")
    _git(r, "checkout", "-q", "pr")
    env = {**os.environ, **_GIT_ENV}
    subprocess.run(["git", "-C", str(r), "merge", "--no-ff", "-m", "sync main 2"],
                   capture_output=True, text=True, env=env)
    _write(r, "fix.py", "total = 1 + 1\nfixed = True\nw = 3\nhand = 7\n")
    head = _commit(r, "sync main 2")
    return {**synced, "merge2": head, "head": head, "prior": prior}


# ---------- the fix delta ----------


def test_delta_carries_the_fix_commit_hunks(synced):
    delta = round_plan.delta_text(synced["repo"], synced["prior"], synced["head"])
    assert "+w = 3" in delta
    assert "fix.py" in delta


def test_delta_omits_the_base_commit_a_clean_sync_merge_brought_in(synced):
    delta = round_plan.delta_text(synced["repo"], synced["prior"], synced["head"])
    assert "base_only.py" not in delta
    assert "subprocess.run(argv)" not in delta


def test_the_security_lens_ignores_a_subprocess_line_added_on_the_base(synced):
    """The lens is fed `delta_text`, so a base author's call site never turns it on."""
    delta = round_plan.delta_text(synced["repo"], synced["prior"], synced["head"])
    assert trust_boundary.surfaces(delta) == []
    # The same range read as a plain diff WOULD report the base's call site.
    assert trust_boundary.surfaces_for_range(synced["repo"], synced["prior"],
                                             synced["head"]) != []


def test_a_second_sync_still_contributes_nothing_when_it_is_clean(synced):
    """Two clean syncs, no fix after them: the delta is only the one fix commit."""
    r, prior = synced["repo"], synced["prior"]
    _git(r, "checkout", "-q", "main")
    _write(r, "base_extra.py", "two = 2\n")
    _commit(r, "more base work")
    _git(r, "checkout", "-q", "pr")
    _git(r, "merge", "--no-ff", "-q", "-m", "sync main again", "main")
    head = _git(r, "rev-parse", "HEAD")
    delta = round_plan.delta_text(r, prior, head)
    assert "+w = 3" in delta
    assert "base_extra.py" not in delta
    assert "two = 2" not in delta


# ---------- a conflicted sync: only the hand resolution ----------


def test_a_conflicted_sync_merge_contributes_only_its_hand_resolution(conflicted):
    delta = round_plan.delta_text(conflicted["repo"], conflicted["prior"],
                                  conflicted["head"])
    assert "+hand = 7" in delta          # the loop's own resolution line
    assert "base_only.py" not in delta   # still never the base's own changes


def test_the_hand_resolution_turns_the_lens_on_when_it_touches_a_surface(conflicted):
    """A resolution that writes a call site IS loop-authored code, so the lens is on."""
    r, prior = conflicted["repo"], conflicted["prior"]
    _git(r, "checkout", "-q", "main")
    _write(r, "fix.py", "import subprocess\nsubprocess.run(['ls'])\n")
    _commit(r, "base work adds a call site in fix.py")
    _git(r, "checkout", "-q", "pr")
    env = {**os.environ, **_GIT_ENV}
    subprocess.run(["git", "-C", str(r), "merge", "--no-ff", "-m", "sync 3"],
                   capture_output=True, text=True, env=env)
    _write(r, "fix.py", "total = 1 + 1\nfixed = True\nw = 3\n"
                        "subprocess.run(['ls'])\n")
    head = _commit(r, "sync 3")
    delta = round_plan.delta_text(r, prior, head)
    surfaces = trust_boundary.surfaces(delta)
    assert [s["surface"] for s in surfaces] == ["argv-subprocess"]
    assert surfaces[0]["path"] == "fix.py"


# ---------- degenerate ranges ----------


def test_delta_is_empty_when_prior_equals_head(synced):
    assert round_plan.delta_text(synced["repo"], synced["head"],
                                 synced["head"]) == ""


def test_delta_is_empty_when_git_fails(synced):
    assert round_plan.delta_text(synced["repo"], "deadbeef" * 5,
                                 synced["head"]) == ""


def test_delta_of_a_plain_fix_chain_is_every_fix_commit(synced):
    """No sync involved: every first-parent commit in the range is a fix."""
    r = synced["repo"]
    _write(r, "fix.py", "total = 1 + 1\nfixed = True\nw = 3\nv = 4\n")
    head = _commit(r, "fix round 3")
    delta = round_plan.delta_text(r, synced["prior"], head)
    assert "+w = 3" in delta
    assert "+v = 4" in delta


# ---------- the §D3 constants ----------


def test_the_delta_constants_match_the_design():
    assert round_plan.SMALL_DIFF_LINES == 300
    assert round_plan.DELTA_CHECK == "delta-check"
