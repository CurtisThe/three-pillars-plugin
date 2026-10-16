"""Tests for origin_blame — a finding's origin computed from git blame.

design: review-convergence (Task 2.1, detailed-design-pr-loop §B)

Behavior 4 on a fixture repo: round 1's head, one loop fix commit, a blocker on
the fix commit's line → `origin: "regression"` with `origin_source: "blame"`;
the same finding on untouched base code → `original`. `round_heads` reads each
`r<N>[.1]/angles.json` manifest's `head` in round order; `fix_commits` is the
first-parent, no-merge range after round 1's head. The schema declares
`origin_source` (enum blame|reviewer).
Oracle: example — exact values on a real tmp git repo (test-fragility).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).parent))

import origin_blame  # noqa: E402

# scripts/ → tp-pr-iterate/ → schemas/ (the schema sits one level above scripts).
SCHEMA_PATH = (Path(__file__).resolve().parent.parent
               / "schemas" / "normalized-finding.v1.json")

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


def _manifest(round_dir, head):
    round_dir.mkdir(parents=True, exist_ok=True)
    (round_dir / "angles.json").write_text(
        json.dumps({"round": 1, "head": head}), encoding="utf-8")


def _finding(**over) -> dict:
    base = {"source": "code-review", "file": "a.py", "line_range": [1, 1],
            "summary": "x", "verdict": "structural"}
    base.update(over)
    return base


@pytest.fixture()
def repo(tmp_path):
    """A PR branch: one base commit (round 1's head) then one loop fix commit."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.name", "t")
    _git(r, "config", "user.email", "t@t")
    _write(r, "a.py", "one = 1\ntwo = 2\nthree = 3\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "base")
    return r


# ---------- round_heads ----------


def test_round_heads_reads_manifests_in_round_order(tmp_path):
    rounds = tmp_path / "rounds"
    _manifest(rounds / "r2", "h2")
    _manifest(rounds / "r1", "h1")
    _manifest(rounds / "r1.1", "h1.1")
    _manifest(rounds / "r10", "h10")
    assert origin_blame.round_heads(rounds) == ["h1", "h1.1", "h2", "h10"]


def test_round_heads_skips_unreadable_manifests_and_absent_dir(tmp_path):
    rounds = tmp_path / "rounds"
    _manifest(rounds / "r1", "h1")
    bad = rounds / "r2"
    bad.mkdir(parents=True)
    (bad / "angles.json").write_text("{not json", encoding="utf-8")
    no_head = rounds / "r3"
    no_head.mkdir(parents=True)
    (no_head / "angles.json").write_text(json.dumps({"round": 3}), encoding="utf-8")
    (rounds / "r4").write_text("a file, not a round dir", encoding="utf-8")
    (rounds / "notes").mkdir()
    assert origin_blame.round_heads(rounds) == ["h1"]
    assert origin_blame.round_heads(tmp_path / "absent") == []


# ---------- fix_commits ----------


def test_fix_commits_is_the_range_after_round_1_head(repo):
    first_head = _git(repo, "rev-parse", "HEAD")
    _write(repo, "a.py", "one = 1\ntwo = 2\nthree = 33\nfour = 4\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fix round 2")
    head = _git(repo, "rev-parse", "HEAD")
    assert origin_blame.fix_commits(repo, first_head, head) == {head}
    assert origin_blame.fix_commits(repo, head, head) == set()


# ---------- classify: blame-computed origin ----------


def test_blocker_on_a_fix_line_is_a_regression(repo):
    first_head = _git(repo, "rev-parse", "HEAD")
    _write(repo, "a.py", "one = 1\ntwo = 2\nthree = 33\nfour = 4\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fix round 2")
    head = _git(repo, "rev-parse", "HEAD")

    out = origin_blame.classify(
        [_finding(line_range=[3, 3]), _finding(line_range=[4, 4]),
         _finding(line_range=[1, 1])],
        cwd=repo, head=head, first_head=first_head)
    assert [(f["origin"], f["origin_source"]) for f in out] == [
        ("regression", "blame"), ("regression", "blame"), ("original", "blame")]


def test_fix_commit_in_an_earlier_round_still_reads_regression(repo):
    """Any loop fix commit after round 1's head counts, not only round N-1's."""
    first_head = _git(repo, "rev-parse", "HEAD")
    _write(repo, "a.py", "one = 1\ntwo = 22\nthree = 3\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fix round 2")
    _write(repo, "a.py", "one = 1\ntwo = 22\nthree = 3\nfour = 4\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fix round 3")
    head = _git(repo, "rev-parse", "HEAD")

    out = origin_blame.classify([_finding(line_range=[2, 2])], cwd=repo, head=head,
                                first_head=first_head)
    assert (out[0]["origin"], out[0]["origin_source"]) == ("regression", "blame")


def test_sentinel_passes_through_without_origin_fields(repo):
    sentinel = {"source": "no-angles", "file": "<review-output:timeout>",
                "line_range": [0, 0], "summary": "DEGRADED", "verdict": "minor"}
    out = origin_blame.classify([sentinel], cwd=repo, head=_git(repo, "rev-parse", "HEAD"),
                                first_head="other")
    assert out == [sentinel]
    assert out[0] is not sentinel
    assert "origin" not in out[0] and "origin_source" not in out[0]


def test_classify_never_mutates_the_findings_it_is_given(repo):
    first_head = _git(repo, "rev-parse", "HEAD")
    _write(repo, "a.py", "one = 1\ntwo = 2\nthree = 33\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fix round 2")
    head = _git(repo, "rev-parse", "HEAD")

    finding = _finding(line_range=[3, 3], origin="original", fragility_class="blocklist")
    before = dict(finding)
    out = origin_blame.classify([finding], cwd=repo, head=head, first_head=first_head)
    assert finding == before
    assert out[0] is not finding
    assert out[0]["origin"] == "regression"
    assert out[0]["fragility_class"] == "blocklist"


# ---------- schema: origin_source ----------


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_schema_path_resolves_to_the_tp_pr_iterate_schemas_dir():
    assert SCHEMA_PATH.name == "normalized-finding.v1.json"
    assert SCHEMA_PATH.parent.name == "schemas"
    assert SCHEMA_PATH.parent.parent.name == "tp-pr-iterate"


def test_schema_declares_origin_source_enum_next_to_origin():
    props = _schema()["properties"]
    assert props.get("origin_source") == {"type": "string",
                                         "enum": ["blame", "reviewer"]}
    names = list(props)
    assert names.index("origin_source") == names.index("origin") + 1


def test_classified_finding_validates_against_the_schema(repo):
    first_head = _git(repo, "rev-parse", "HEAD")
    _write(repo, "a.py", "one = 1\ntwo = 2\nthree = 33\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fix round 2")
    head = _git(repo, "rev-parse", "HEAD")

    validator = Draft202012Validator(_schema())
    for finding in origin_blame.classify(
            [_finding(line_range=[3, 3]), _finding(line_range=[0, 0], origin="regression")],
            cwd=repo, head=head, first_head=first_head):
        validator.validate(finding)


def test_schema_rejects_an_unknown_origin_source():
    import jsonschema

    with pytest.raises(jsonschema.ValidationError):
        Draft202012Validator(_schema()).validate(
            _finding(origin="regression", origin_source="guessed"))
