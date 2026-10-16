"""Tests for origin_blame across a base-sync merge and on the reviewer fallback.

design: review-convergence (Task 2.1, detailed-design-pr-loop §B)

`fix_commits` walks `first_head..head` with `--first-parent --no-merges`, so a
mid-loop sync of the base branch and the commits it brings in are NOT loop fix
commits: lines that arrived that way blame to a base commit and stay
`origin: "original"`. A finding with no file/line, a blame error, or round 1
(`first_head == head`) keeps the reviewer's tag through `finding_fields.normalize`
and is recorded as `origin_source: "reviewer"`.
Oracle: example — exact values on a real tmp git repo (test-fragility).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import origin_blame  # noqa: E402

_GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
            "GIT_CONFIG_NOSYSTEM": "1", "HOME": "/nonexistent"}


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


def _finding(**over) -> dict:
    base = {"source": "code-review", "file": "a.py", "line_range": [1, 1],
            "summary": "x", "verdict": "structural"}
    base.update(over)
    return base


@pytest.fixture()
def synced(tmp_path):
    """PR branch: round-1 head → loop fix commit → sync merge of `master` → fix commit."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.name", "t")
    _git(r, "config", "user.email", "t@t")
    _write(r, "a.py", "one = 1\ntwo = 2\nthree = 3\n")
    _commit(r, "base")
    first_head = _git(r, "rev-parse", "HEAD")

    # The base branch moves on its own (a master commit the loop later syncs in).
    _git(r, "checkout", "-q", "-b", "master")
    _write(r, "a.py", "one = 1\ntwo = 2\nthree = 3\nmaster_only = 9\n")
    master_commit = _commit(r, "master work")
    _git(r, "checkout", "-q", "main")

    _write(r, "a.py", "one = 1\ntwo = 22\nthree = 3\n")
    loop_fix = _commit(r, "fix round 2")
    _git(r, "merge", "--no-ff", "-q", "-m", "sync master", "master")
    merge_commit = _git(r, "rev-parse", "HEAD")
    _write(r, "a.py", "one = 1\ntwo = 22\nthree = 3\nmaster_only = 9\npost = 10\n")
    head = _commit(r, "fix round 3")
    return {"repo": r, "first_head": first_head, "master_commit": master_commit,
            "loop_fix": loop_fix, "merge_commit": merge_commit, "head": head}


# ---------- a sync merge's lines stay original ----------


def test_fix_commits_excludes_the_sync_merge_and_the_commits_it_brings(synced):
    commits = origin_blame.fix_commits(synced["repo"], synced["first_head"], synced["head"])
    assert commits == {synced["loop_fix"], synced["head"]}
    assert synced["merge_commit"] not in commits
    assert synced["master_commit"] not in commits


def test_lines_that_arrived_in_the_sync_merge_stay_original(synced):
    """Line 4 (`master_only`) came from master through the merge, not from a fix."""
    out = origin_blame.classify(
        [_finding(line_range=[2, 2]), _finding(line_range=[4, 4])],
        cwd=synced["repo"], head=synced["head"], first_head=synced["first_head"])
    assert [(f["origin"], f["origin_source"]) for f in out] == [
        ("regression", "blame"), ("original", "blame")]


def test_blame_beats_a_wrong_reviewer_tag(synced):
    out = origin_blame.classify([_finding(line_range=[4, 4], origin="regression"),
                                 _finding(line_range=[5, 5], origin="original")],
                                cwd=synced["repo"], head=synced["head"],
                                first_head=synced["first_head"])
    assert [(f["origin"], f["origin_source"]) for f in out] == [
        ("original", "blame"), ("regression", "blame")]


# ---------- the reviewer fallback ----------


def test_finding_without_a_line_keeps_the_reviewer_tag(synced):
    out = origin_blame.classify(
        [_finding(line_range=[0, 0], origin="regression"),
         _finding(line_range=None, origin="original")],
        cwd=synced["repo"], head=synced["head"], first_head=synced["first_head"])
    assert [(f["origin"], f["origin_source"]) for f in out] == [
        ("regression", "reviewer"), ("original", "reviewer")]


def test_finding_without_a_file_keeps_the_reviewer_tag(synced):
    finding = _finding(file="", line_range=[0, 0], origin="regression")
    out = origin_blame.classify([finding], cwd=synced["repo"], head=synced["head"],
                                first_head=synced["first_head"])
    assert (out[0]["origin"], out[0]["origin_source"]) == ("regression", "reviewer")


def test_blame_error_falls_back_and_an_unknown_tag_becomes_unclassified(synced):
    """A file that does not exist at `head` cannot be blamed → reviewer fallback,
    and `finding_fields.normalize` maps an unknown tag to `unclassified`."""
    finding = _finding(file="deleted/gone.py", line_range=[3, 3], origin="maybe-new")
    out = origin_blame.classify([finding], cwd=synced["repo"], head=synced["head"],
                                first_head=synced["first_head"])
    assert (out[0]["origin"], out[0]["origin_source"]) == ("unclassified", "reviewer")


def test_round_1_first_head_equals_head_is_all_reviewer_tagged(synced):
    finding = _finding(line_range=[2, 2], origin="regression")
    out = origin_blame.classify([finding], cwd=synced["repo"], head=synced["head"],
                                first_head=synced["head"])
    assert (out[0]["origin"], out[0]["origin_source"]) == ("regression", "reviewer")


def test_missing_reviewer_tag_falls_back_to_unclassified(synced):
    finding = _finding(line_range=[0, 0])
    out = origin_blame.classify([finding], cwd=synced["repo"], head=synced["head"],
                                first_head=synced["first_head"])
    assert (out[0]["origin"], out[0]["origin_source"]) == ("unclassified", "reviewer")
