"""round_plan.plan — round n ≥ 2: ONE delta-check angle, based on the prior head.

design: review-convergence (Task 4.4, detailed-design-pr-loop §D3)

Review bar: a later round reviews only the fix delta since the last round that
actually produced a review — `mode: delta`, `base` = that round's head (never
`pr_base`, never the whole PR). It runs exactly ONE angle, `delta-check`, an Opus
confirmer pointed at the prior round's `tail/findings.json`: no finders, no Opus
check, so `rulings_path` may be None and a config that declares angles cannot put
anything else in the round. `diff_lines` still measures the WHOLE PR, because the
growth budget is the PR's. When no prior round qualifies (a lost rounds dir, or
the only round reviewed this very head) the round REFUSES with
`prepare-refused: no prior reviewed head` — never silently widens to the full diff.
Oracle: example — exact angle names/counts and exact shas on a real tmp git repo
with real round dirs (test-fragility).
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

PR_URL = "https://github.com/o/r/pull/9"

BLOCKER = {"source": "code-review", "file": "fix.py", "line_range": [1, 1],
           "summary": "wrong total", "verdict": "structural"}
DEGRADED = {"source": "no-angles", "summary": "no angle ran", "verdict": "structural"}
ONE_ANGLE = {"review": {"angles": [{"name": "my-angle", "role": "confirmer",
                                    "model": "opus", "prompt": "look at mine"}]}}

_ENVELOPE = {"schema": "tp-pr-iterate/round-tail/v1", "round": 1,
             "head_reviewed": "", "head_after": "",
             "tally": {"P": 1, "X": 0, "T": 0, "C": 0, "blocking": 1, "degraded": 0},
             "downgraded": 0, "notes": 0, "action": "fix", "fix_commit": None,
             "terminal": None, "converged": False,
             "budget": {"iteration": 1, "round_cap": 5, "signal": None, "holding": []},
             "finalizer_stop": None, "summary": "r1"}


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


def _round(rounds_dir, name, head, findings):
    """One completed round: manifest + tail findings + the envelope `prepare` reads."""
    rd = Path(rounds_dir) / name
    (rd / "tail").mkdir(parents=True, exist_ok=True)
    (rd / "angles.json").write_text(json.dumps({"head": head}), encoding="utf-8")
    (rd / "tail" / "findings.json").write_text(json.dumps(findings), encoding="utf-8")
    (rd / "tail" / "envelope.json").write_text(
        json.dumps({**_ENVELOPE, "head_reviewed": head, "head_after": head}),
        encoding="utf-8")
    return rd


@pytest.fixture()
def pr(tmp_path):
    """main: base commit, PR commit `A` (the r1 head), fix commit `B` = head."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.name", "t")
    _git(r, "config", "user.email", "t@t")
    _write(r, "fix.py", "total = 1 + 1\n")
    base = _commit(r, "base")
    _write(r, "fix.py", "total = 1 + 1\nfixed = True\n")
    a = _commit(r, "A pr commit")
    _write(r, "fix.py", "total = 2\nfixed = True\n")
    b = _commit(r, "B fix")
    root = tmp_path / "root"
    _round(root / "rounds" / "9", "r1", a, [BLOCKER])
    return {"repo": r, "root": root, "base": base, "A": a, "B": b,
            "rounds": root / "rounds" / "9"}


def _plan(pr, *, head=None, **kw):
    """`plan` for the fixture PR at `head` (default the fix commit B)."""
    return round_plan.plan(kw.pop("config", None), root=pr["root"], pr_url=PR_URL,
                           pr_base=pr["base"], head=head or pr["B"],
                           repo=str(pr["repo"]), **kw)


# ---------- Behavior 10: the delta round's shape ----------


def test_round_two_is_a_delta_on_the_prior_head(pr):
    got = _plan(pr)
    assert got["round"] == 2
    assert got["mode"] == "delta"
    assert got["base"] == pr["A"]           # the r1 head — not pr_base
    assert got["pr_base"] == pr["base"]     # the PR base is still named


def test_a_delta_round_runs_exactly_the_delta_check(pr):
    entries = _plan(pr)["angles"]
    assert [a["name"] for a in entries] == [round_plan.DELTA_CHECK]
    assert round_plan.DELTA_CHECK == "delta-check"


def test_the_delta_check_is_an_opus_confirmer(pr):
    one = _plan(pr)["angles"][0]
    assert (one["role"], one["model"]) == ("confirmer", "opus")
    assert "advisory" not in one


def test_a_delta_round_dispatches_no_finder_and_no_opus_check(pr):
    names = [a["name"] for a in _plan(pr)["angles"]]
    for other in ("combined", "opus-check", "security", "correctness"):
        assert other not in names


def test_a_delta_round_needs_no_rulings(pr):
    assert _plan(pr, rulings_path=None)["round"] == 2


def test_declared_angles_add_nothing_to_a_delta_round(pr):
    assert [a["name"] for a in _plan(pr, config=ONE_ANGLE)["angles"]] == [
        round_plan.DELTA_CHECK]


def test_diff_lines_still_measures_the_whole_pr(pr):
    """base..B is 3 counted lines (2 added, 1 removed); the fix delta alone is 2."""
    got = _plan(pr)
    assert got["diff_lines"] == 3
    assert "+total = 2" in round_plan.delta_text(pr["repo"], got["base"], pr["B"])


# ---------- the prompt reads the prior round's findings ----------


def test_the_prompt_names_the_prior_rounds_findings(pr):
    prompt = _plan(pr)["angles"][0]["prompt"]
    assert str(pr["rounds"] / "r1" / "tail" / "findings.json") in prompt


def test_the_prompt_covers_the_delta_and_the_prior_blockers(pr):
    prompt = _plan(pr)["angles"][0]["prompt"]
    assert "delta" in prompt.lower()
    for word in ("blocker", "closed"):
        assert word in prompt.lower()
    assert "new" in prompt.lower()


def test_delta_check_angle_reports_the_prior_findings_path_directly():
    one = round_plan.delta_check_angle("/x/rounds/9/r1/tail/findings.json")
    assert one["name"] == round_plan.DELTA_CHECK
    assert (one["role"], one["model"]) == ("confirmer", "opus")
    assert "/x/rounds/9/r1/tail/findings.json" in one["prompt"]


# ---------- refusal: no prior reviewed head ----------


def test_a_degraded_only_prior_round_refuses(pr):
    _round(pr["rounds"], "r1", pr["A"], [DEGRADED])
    with pytest.raises(ValueError) as exc:
        _plan(pr)
    assert str(exc.value).startswith("prepare-refused: no prior reviewed head")


def test_a_round_that_reviewed_this_very_head_refuses(pr):
    _round(pr["rounds"], "r1", pr["B"], [BLOCKER])
    with pytest.raises(ValueError) as exc:
        _plan(pr)
    assert str(exc.value).startswith("prepare-refused: no prior reviewed head")


def test_a_round_dir_that_names_no_head_refuses(pr):
    """The round dir exists (so this IS round 2) but its manifest lost `head`."""
    (pr["rounds"] / "r1" / "angles.json").write_text(json.dumps({"round": 1}),
                                                     encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        _plan(pr)
    assert str(exc.value).startswith("prepare-refused: no prior reviewed head")


def test_the_refused_round_never_falls_back_to_the_full_pr_diff(pr):
    (pr["rounds"] / "r1" / "tail" / "findings.json").unlink()  # r1 reviewed nothing
    with pytest.raises(ValueError):
        _plan(pr)


def test_the_refusal_is_a_planrefused(pr):
    _round(pr["rounds"], "r1", pr["A"], [DEGRADED])
    with pytest.raises(round_plan.PlanRefused):
        _plan(pr)
