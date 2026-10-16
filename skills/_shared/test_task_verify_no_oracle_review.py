"""test_task_verify_no_oracle_review.py — ``check`` and a cheap rung's no-oracle PASS.

design: ladder-diagnose-and-size-pins (Part N)

A cheap rung with no runnable oracle is accepted only by an Opus diff-review verdict
(``review=``), recorded as ``accepted-by-review``; a missing verdict fails closed, an
unparseable one is a reject, a row with an oracle never reads one, and ``opus`` is unchanged.
"""
from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

import no_oracle_review
import task_attempts
import task_verify
from attempt_fixture import DD, commit, commit_pair, make_seat, task_row

ACCEPT = '{"verdict": "accept", "reason": "adds A=2 as the task asks"}'
REJECT = '{"verdict": "reject", "reason": "A is still 1"}'
NO_ORACLE = "no oracle (a cheap rung needs a runnable Test)"
RUNNER = f"{shlex.quote(sys.executable)} -m pytest -q"
GREEN = "def test_a():\n    assert 1 == 1\n"


def _attempt(tmp_path):
    _seat, wt = make_seat(tmp_path)
    att = task_attempts.open_attempt(wt, "1.1", DD)
    commit(Path(att["attempt_dir"]), {"skills/a.py": "A = 2\n"})
    return att


def _check(att, row=None, *, rung="local", review=None, runner=None):
    return task_verify.check(att, row or task_row(), runner, rung=rung, timeout=60,
                             review=review)


@pytest.mark.parametrize("rung", ["local", "sonnet"])
def test_missing_verdict_fails_closed_and_asks_for_a_review(tmp_path, rung):
    att = _attempt(tmp_path)
    res = _check(att, rung=rung)
    assert (res["verdict"], res["reason"], res["exit"]) == ("FAIL", NO_ORACLE, 1)
    assert res["needs_review"] is True and res["unverified"] is False
    assert res["accepted_by"] is None
    blank = _check(att, rung=rung, review="  ")  # a blank reply is a missing one
    assert (blank["verdict"], blank["reason"]) == ("FAIL", NO_ORACLE)


def test_a_lint_or_scope_failure_is_not_reviewable(tmp_path):
    wt = make_seat(tmp_path)[1]
    att = task_attempts.open_attempt(wt, "1.1", DD)
    commit(Path(att["attempt_dir"]), {"skills/a.py": "A = 2\n", "skills/b.py": "B = 1\n"})
    res = _check(att, review=ACCEPT)
    assert (res["verdict"], res["reason"]) == ("FAIL", "unlisted file: skills/b.py")
    assert res["needs_review"] is False


@pytest.mark.parametrize("text", ["", "looks good", '{"verdict": "ACCEPT"}', "{not json",
                                  '{"verdict": "accepted"}'])
def test_unparseable_verdict_is_a_reject(tmp_path, text):
    res = _check(_attempt(tmp_path), review=text or "x")
    assert res["verdict"] == "FAIL" and res["exit"] == 1
    assert res["reason"].startswith("review-rejected: review verdict unparseable")
    assert res["needs_review"] is False and not res["reason"].startswith("no oracle")


def test_reject_is_a_failed_attempt_carrying_the_reason(tmp_path):
    res = _check(_attempt(tmp_path), review=REJECT)
    assert (res["verdict"], res["reason"]) == ("FAIL", "review-rejected: A is still 1")
    assert res["unverified"] is False


@pytest.mark.parametrize("rung", ["local", "sonnet"])
def test_accept_lands_as_accepted_by_review_never_a_test_pass(tmp_path, rung):
    att = _attempt(tmp_path)
    res = _check(att, rung=rung, review=ACCEPT)
    assert (res["verdict"], res["exit"]) == ("PASS", 0)
    assert res["unverified"] is True and res["accepted_by"] == "review"
    assert res["commands"] == [] and res["red_at_base"] == "n/a"
    assert res["reason"] == "accepted-by-review: adds A=2 as the task asks"
    out = task_verify.land(att)  # a PASS check of this commit lands
    assert out["exit"] == 0 and out["method"] == "ff"


def test_accept_does_not_survive_an_edit_after_the_check(tmp_path):
    att = _attempt(tmp_path)
    assert _check(att, review=ACCEPT)["verdict"] == "PASS"
    commit(Path(att["attempt_dir"]), {"skills/a.py": "A = 3\n"})
    assert _check(att, review=ACCEPT)["reason"] == "edited-after-pass"


@pytest.mark.parametrize("review", [ACCEPT, REJECT, "garbage", None])
def test_a_row_with_an_oracle_never_takes_the_review_path(tmp_path, review):
    _seat, wt = make_seat(tmp_path)
    att = task_attempts.open_attempt(wt, "1.1", DD)
    commit_pair(Path(att["attempt_dir"]), {"skills/test_a.py": "def test_a():\n    assert 1 == 2\n"},
                {"skills/a.py": "A = 2\n"})
    row = task_row(targets="`skills/test_a.py::test_a`")
    res = _check(att, row, review=review, runner=RUNNER)  # red: the verdict cannot save it
    assert (res["verdict"], res["reason"]) == ("FAIL", "red test")
    assert res["needs_review"] is False and res["accepted_by"] is None
    att2 = task_attempts.open_attempt(wt, "1.2", DD)
    commit_pair(Path(att2["attempt_dir"]), {"skills/test_a.py": GREEN}, {"skills/a.py": "A = 2\n"})
    res = _check(att2, row, review=REJECT, runner=RUNNER)  # green: a reject cannot fail it
    assert (res["verdict"], res["unverified"], res["accepted_by"]) == ("PASS", False, None)


@pytest.mark.parametrize("review", [None, ACCEPT, REJECT, "garbage"])
def test_opus_rung_is_unchanged_and_ignores_the_verdict(tmp_path, review):
    res = _check(_attempt(tmp_path), rung="opus", review=review)
    assert (res["verdict"], res["unverified"], res["accepted_by"]) == ("PASS", True, None)
    assert res["needs_review"] is False and "accepted-by-review" not in res["reason"]


def test_a_refused_runner_with_a_row_that_has_targets_still_needs_a_review(tmp_path):
    att = _attempt(tmp_path)
    row = task_row(targets="`skills/test_a.py::test_a`")  # declared, but no runner resolved
    res = task_verify.check(att, row, None, rung="local", timeout=60, runner_why="no-runner")
    assert res["reason"] == "no oracle: no-runner" and res["needs_review"] is True
    res = task_verify.check(att, row, None, rung="local", timeout=60, runner_why="no-runner",
                            review=ACCEPT)
    assert (res["verdict"], res["accepted_by"]) == ("PASS", "review")


def test_cli_check_reads_the_review_reply_file(tmp_path):
    seat, wt = make_seat(tmp_path)
    plan = Path(wt, DD, "plan.md")
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text("# p\n\n## Phase 1: T\n\n### Task 1.1: Doc\n**File**: `skills/a.py`\n"
                    "**Targets**: none\n**Red**: x\n**Green**: y\n", encoding="utf-8")
    commit(wt, {}, "plan")
    att = task_attempts.open_attempt(wt, "1.1", DD)
    commit(Path(att["attempt_dir"]), {"skills/a.py": "A = 2\n"})
    script = str(Path(task_verify.__file__).resolve())
    base = [sys.executable, script, "check", "--root", str(wt), "--attempt", att["attempt_id"],
            "--plan", f"{DD}/plan.md", "--phase", "1", "--rung", "local"]
    first = subprocess.run(base, capture_output=True, text=True)
    assert first.returncode == 1 and json.loads(first.stdout)["needs_review"] is True
    reply = tmp_path / "v.txt"
    reply.write_text(ACCEPT, encoding="utf-8")
    second = subprocess.run([*base, "--review-reply", str(reply)], capture_output=True, text=True)
    assert second.returncode == 0, second.stdout
    out = json.loads(second.stdout)
    assert out["accepted_by"] == "review" and out["unverified"] is True
    missing = subprocess.run([*base, "--review-reply", str(tmp_path / "nope.txt")],
                             capture_output=True, text=True)
    assert missing.returncode == 1 and json.loads(missing.stdout)["reason"].startswith("no oracle")
    prompt = subprocess.run([sys.executable, str(Path(no_oracle_review.__file__)), "prompt",
                             "--root", str(wt), "--attempt", att["attempt_id"],
                             "--plan", f"{DD}/plan.md", "--phase", "1"],
                            capture_output=True, text=True)
    assert prompt.returncode == 0 and "+A = 2" in prompt.stdout and "**Green**: y" in prompt.stdout
