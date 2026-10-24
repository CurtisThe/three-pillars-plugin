"""`loop_driver.run_round` asks the review-stop question before the converge label.

design: seat-escalate-first (Phase 1, Task 1.4)

Oracle: example — the label calls, the decision and the seeded record for fixed rounds.
"""
from __future__ import annotations

import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import converge  # noqa: E402
import iterate_state  # noqa: E402
import loop_driver  # noqa: E402

NOW = datetime(2026, 10, 21, 12, 0, 0, tzinfo=timezone.utc)
PR = "https://github.com/o/r/pull/7"
HEAD = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
OLD = "0" * 40
CFG = {"review": {"expects_copilot": False}, "ci": {"expects_github_checks": False}}


def _note(summary):
    return {"file": "a.py", "line_range": [1, 2], "summary": summary, "title": summary,
            "verdict": "minor", "blocking": False, "class": "T"}


NOTES = [_note("tighten the loop"), _note("rename the helper")]


def _state(head, *, last=None, last_round="r1", iteration=3, **extra):
    return {
        "phase": "fixing", "iteration": iteration, "max_iterations": 8,
        "max_wall_clock_sec": 14400, "started_at": NOW.isoformat(), "last_verdict": "minor-only",
        "transitions": [], "cumulative_diff_lines": 0, "original_diff_lines": 100,
        "consecutive_structural_rounds": 0, "last_loop_sha": None,
        "last_comment_seen_at": None, "last_codereview_head_sha": head,
        "budget_last_head": last if last is not None else head,
        "budget_last_round": last_round, "budget_last_action": "noop", **extra,
    }


def _run(state, findings, *, head=HEAD, ordinal="r1"):
    labels, unlabels = [], []
    res = loop_driver.run_round(
        state, head_sha=head, codereview_findings=findings, reviewed=None,
        unresolved_actionable=0, ci_rollup=[], config=CFG, now=NOW, pr_url=PR,
        label_fn=lambda u, lbl: labels.append(lbl),
        unlabel_fn=lambda u, lbl: unlabels.append(lbl), proof_ok=True, ordinal=ordinal)
    return res, labels, unlabels


def test_zero_notes_labels_without_a_stop():
    res, labels, _ = _run(_state(HEAD), [])
    assert "tp:ready-for-human-merge" in labels
    assert "finalizer_stop" not in res and res["terminal"].startswith("two-stable")


def test_notes_return_a_decision_stop_and_no_label():
    res, labels, _ = _run(_state(HEAD), NOTES)
    assert res["finalizer_stop"]["signal"] == "decision"
    assert res["terminal"] is None and labels == []
    assert res["state"]["phase"] != "awaiting-human-review"


def test_same_head_stop_record_labels():
    record = {"choice": "stop", "head": HEAD, "iteration": 3}
    res, labels, _ = _run(_state(HEAD, review_stop=record), NOTES)
    assert "tp:ready-for-human-merge" in labels and "finalizer_stop" not in res


def test_fix_record_no_commit_asks_again_with_the_same_key():
    record = {"choice": "fix", "head": OLD, "iteration": 3}
    first, labels, _ = _run(_state(HEAD, review_stop=record), NOTES)
    again, labels2, _ = _run(_state(HEAD, review_stop=record), NOTES)
    assert labels == [] and labels2 == []
    assert first["finalizer_stop"]["detail"]["notes"] == again["finalizer_stop"]["detail"]["notes"]


def test_delta_round_with_new_notes_asks_a_new_stop():
    record = {"choice": "fix", "head": OLD, "iteration": 3}
    new = [_note("handle the empty list")]
    res, labels, _ = _run(_state(OLD, last_round="r1", review_stop=record,
                                 budget_last_action="fix"),
                          new, head=HEAD, ordinal="r2")
    assert res["state"]["iteration"] == 4 and labels == []
    assert "handle the empty list" in res["finalizer_stop"]["detail"]["question"]


def test_seed_keeps_the_review_stop_record(tmp_path):
    state_path = tmp_path / "iterate-state.7.v1.json"
    converge._seed_state(state_path, HEAD)
    seeded = json.loads(state_path.read_text(encoding="utf-8"))
    record = {"choice": "stop", "head": HEAD, "ruling_id": "r-1", "iteration": 3}
    iterate_state.write_state_atomic(state_path, {**seeded, "review_stop": record})
    angle = tmp_path / "r1.txt"
    angle.write_text('```json\n{"findings": []}\n```\n', encoding="utf-8")
    seen = {}

    def run_round_fn(stdin):
        text = Path(stdin["state_path"]).read_text(encoding="utf-8")
        seen["record"] = json.loads(text).get("review_stop")
        return {"converged": True, "terminal": "two-stable", "seen": seen["record"]}

    def run_git(args):
        return (0, HEAD + "\n", "") if args[:2] == ["git", "rev-parse"] else (0, "3\t1\tf.py\n", "")

    converge.converge(
        base="b0", head=HEAD, pr_url=PR, config={"review": {"automation_identities": ["bot"]}},
        angle_files=[str(angle)], proof_root=tmp_path / "proof", state_path=state_path,
        post_fn=lambda u, b: True, run_round_fn=run_round_fn,
        comments_fn=lambda u: [], self_login_fn=lambda: "bot", run_git=run_git,
        out=io.StringIO(), err=io.StringIO())
    assert seen.get("record") == record
