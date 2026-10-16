"""round_plan.prior_reviewed_head — the base a delta (or a `.1` retry) reviews against.

design: review-convergence (Task 4.2, detailed-design-pr-loop §D3)

Review bar: round n ≥ 2 reviews only the fix delta since the last round that
actually produced a review — the newest prior round whose `tail/findings.json` is
not degraded-only and whose head differs from the head being prepared. A `.1`
rerun-review runs on the SAME head as its parent round, so it is skipped and the
base inherits from the parent's parent: the delta is never empty. A round that
reviewed cleanly at the current head is skipped too, so a re-prepare at that head
still diffs against the last *different* reviewed head.
Oracle: example — exact shas on a real tmp git repo + real round dirs
(test-fragility).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import round_plan  # noqa: E402

_GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
            "GIT_CONFIG_NOSYSTEM": "1", "HOME": "/nonexistent"}

BLOCKER = {"source": "code-review", "file": "fix.py", "line_range": [1, 1],
           "summary": "wrong total", "verdict": "structural"}
NOTE = {"source": "code-review", "file": "fix.py", "line_range": [1, 1],
        "summary": "naming", "verdict": "minor"}
DEGRADED = {"source": "no-angles", "summary": "no angle ran", "verdict": "structural"}


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


def _round(rounds_dir, name, head, findings=None, *, raw_manifest=None,
           bad_findings=False):
    """One round dir: `angles.json` manifest + `tail/findings.json`."""
    rd = Path(rounds_dir) / name
    (rd / "tail").mkdir(parents=True, exist_ok=True)
    manifest = raw_manifest if raw_manifest is not None else {"head": head}
    (rd / "angles.json").write_text(json.dumps(manifest), encoding="utf-8")
    if findings is not None or bad_findings:
        payload = "not json" if bad_findings else json.dumps(findings)
        (rd / "tail" / "findings.json").write_text(payload, encoding="utf-8")
    return rd


@pytest.fixture()
def repo(tmp_path):
    """main: base commit A, then fix commit B = head."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.name", "t")
    _git(r, "config", "user.email", "t@t")
    _write(r, "fix.py", "total = 1 + 1\n")
    a = _commit(r, "A base")
    _write(r, "fix.py", "total = 2\n")
    b = _commit(r, "B fix")
    return {"repo": r, "A": a, "B": b, "rounds": tmp_path / "rounds"}


# ---------- the §D3 rerun row ----------


def test_a_degraded_round_at_the_current_head_falls_back_to_its_parent(repo):
    """r1 clean-with-blockers at A, r2 degraded at B → r2.1's base is A."""
    _round(repo["rounds"], "r1", repo["A"], [BLOCKER])
    _round(repo["rounds"], "r2", repo["B"], [DEGRADED])
    assert round_plan.prior_reviewed_head(repo["rounds"], repo["B"]) == repo["A"]


def test_the_inherited_base_gives_a_non_empty_delta(repo):
    _round(repo["rounds"], "r1", repo["A"], [BLOCKER])
    _round(repo["rounds"], "r2", repo["B"], [DEGRADED])
    delta = round_plan.delta_text(repo["repo"], repo["A"], repo["B"])
    assert "+total = 2" in delta
    assert delta


def test_a_retry_round_dir_on_the_same_head_is_skipped_too(repo):
    """r2.1 exists at B (its own tail already written): base is still A."""
    _round(repo["rounds"], "r1", repo["A"], [BLOCKER])
    _round(repo["rounds"], "r2", repo["B"], [DEGRADED])
    _round(repo["rounds"], "r2.1", repo["B"], [DEGRADED])
    assert round_plan.prior_reviewed_head(repo["rounds"], repo["B"]) == repo["A"]


def test_a_clean_round_at_the_current_head_is_not_the_base(repo):
    """Preparing again at B: r2 reviewed B cleanly, so the base is still A."""
    _round(repo["rounds"], "r1", repo["A"], [BLOCKER])
    _round(repo["rounds"], "r2", repo["B"], [BLOCKER, NOTE])
    assert round_plan.prior_reviewed_head(repo["rounds"], repo["B"]) == repo["A"]


# ---------- newest-first, and what disqualifies a round ----------


def test_the_newest_qualifying_round_wins(repo):
    _write(repo["repo"], "fix.py", "total = 3\n")
    c = _commit(repo["repo"], "C fix")
    _round(repo["rounds"], "r1", repo["A"], [BLOCKER])
    _round(repo["rounds"], "r2", repo["B"], [NOTE])
    _round(repo["rounds"], "r3", repo["B"], [BLOCKER])
    assert round_plan.prior_reviewed_head(repo["rounds"], c) == repo["B"]


def test_a_round_with_blockers_and_a_sentinel_is_not_degraded_only(repo):
    """A blocker alongside a sentinel means the round DID review -> it is a base."""
    _write(repo["repo"], "fix.py", "total = 3\n")
    c = _commit(repo["repo"], "C fix")
    _round(repo["rounds"], "r1", repo["A"], [BLOCKER])
    _round(repo["rounds"], "r2", repo["B"], [BLOCKER, DEGRADED])
    assert round_plan.prior_reviewed_head(repo["rounds"], c) == repo["B"]


def test_a_degraded_only_round_never_becomes_the_base(repo):
    _round(repo["rounds"], "r1", repo["A"], [BLOCKER])
    _round(repo["rounds"], "r2", repo["B"], [DEGRADED])
    _round(repo["rounds"], "r3", repo["B"], [DEGRADED])
    assert round_plan.prior_reviewed_head(repo["rounds"], repo["B"]) == repo["A"]


def test_a_round_with_no_findings_json_is_skipped(repo):
    _round(repo["rounds"], "r1", repo["A"], [BLOCKER])
    _round(repo["rounds"], "r2", repo["B"])  # manifest only, no tail
    assert round_plan.prior_reviewed_head(repo["rounds"], repo["B"]) == repo["A"]


def test_unreadable_findings_or_manifest_skips_the_round(repo):
    _round(repo["rounds"], "r1", repo["A"], [BLOCKER])
    _round(repo["rounds"], "r2", repo["B"], bad_findings=True)
    _round(repo["rounds"], "r3", repo["B"], {"head": repo["B"]})  # not a dict round
    assert round_plan.prior_reviewed_head(repo["rounds"], repo["B"]) == repo["A"]


def test_a_round_dir_with_no_head_in_its_manifest_is_skipped(repo):
    _round(repo["rounds"], "r1", repo["A"], [BLOCKER])
    _round(repo["rounds"], "r2", None, [BLOCKER], raw_manifest={"round": 2})
    assert round_plan.prior_reviewed_head(repo["rounds"], repo["B"]) == repo["A"]


def test_non_round_names_are_ignored(repo):
    """`r2x` / `r1.2` hold a head that would win, so a loose regex would show up."""
    _write(repo["repo"], "fix.py", "total = 3\n")
    c = _commit(repo["repo"], "C fix")
    _round(repo["rounds"], "r1", repo["A"], [BLOCKER])
    _round(repo["rounds"], "r2x", c, [BLOCKER])
    _round(repo["rounds"], "r1.2", c, [BLOCKER])
    _round(repo["rounds"], "review", c, [BLOCKER])
    (repo["rounds"] / "notes.json").write_text("{}", encoding="utf-8")
    assert round_plan.prior_reviewed_head(repo["rounds"], repo["B"]) == repo["A"]


def test_findings_json_that_is_not_a_list_skips_the_round(repo):
    _round(repo["rounds"], "r1", repo["A"], [BLOCKER])
    _round(repo["rounds"], "r2", repo["B"], {"findings": [BLOCKER]})
    assert round_plan.prior_reviewed_head(repo["rounds"], repo["B"]) == repo["A"]


def test_none_when_nothing_qualifies(repo):
    _round(repo["rounds"], "r1", repo["B"], [BLOCKER])
    assert round_plan.prior_reviewed_head(repo["rounds"], repo["B"]) is None


def test_none_when_the_rounds_dir_is_missing(repo):
    assert round_plan.prior_reviewed_head(repo["rounds"] / "gone",
                                          repo["B"]) is None
