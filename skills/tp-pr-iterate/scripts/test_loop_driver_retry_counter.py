"""test_loop_driver_retry_counter.py — the mechanical degraded_review_retries counter.

review-integrity-enforcement Task 2.2 (Finding 4): loop_driver.run_round tracks a
committed-state COUNT of consecutive blocked-no-independent-review rounds, mirroring the
`consecutive_codereview_structural_rounds` idiom. The orchestrator reads it to bound its
bounded re-run (default 1). A converged / non-blocked round resets it to 0.

New file (test_loop_driver.py is far over the split cap and grandfathered).
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import loop_driver  # noqa: E402
import review_merge  # noqa: E402

_CONFIG = {"review": {"expects_copilot": False}, "ci": {"expects_github_checks": False}}
PR = "https://github.com/o/r/pull/1"


def _state(now, **overrides):
    state = {
        "phase": "awaiting-copilot",
        "iteration": 1,
        "max_iterations": 8,
        "max_wall_clock_sec": 14400,
        "started_at": (now - timedelta(hours=1)).isoformat(),
        "transitions": [],
        "cumulative_diff_lines": 0,
        "original_diff_lines": 100,
        "consecutive_structural_rounds": 0,
        "last_loop_sha": None,
        "last_comment_seen_at": None,
        "last_verdict": "minor-only",
        "last_codereview_head_sha": "head1",
        "last_codereview_findings": [],
    }
    state.update(overrides)
    return state


def _run(state, *, findings, proof_ok):
    now = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)
    return loop_driver.run_round(
        state,
        head_sha="head1",
        codereview_findings=findings,
        reviewed=None,
        unresolved_actionable=0,
        ci_rollup=[],
        config=_CONFIG,
        now=now,
        decisions_path=None,
        pr_url=PR,
        label_fn=lambda pr, lbl: None,
        unlabel_fn=lambda pr, lbl: None,
        proof_ok=proof_ok,
    )


def test_blocked_round_increments_from_zero():
    now = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)
    degraded = review_merge.merge_codereview_angles([])  # no-angles sentinel → blocked
    result = _run(_state(now), findings=degraded, proof_ok=False)
    assert result["terminal"] == "blocked-no-independent-review"
    assert result["state"]["degraded_review_retries"] == 1


def test_blocked_round_increments_prior_value():
    now = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)
    degraded = review_merge.merge_codereview_angles([])
    result = _run(_state(now, degraded_review_retries=1), findings=degraded, proof_ok=False)
    assert result["terminal"] == "blocked-no-independent-review"
    assert result["state"]["degraded_review_retries"] == 2


def test_converged_round_resets_to_zero():
    now = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)
    # real-clean findings + proof_ok True + minor-only + zero unresolved → two-stable
    result = _run(_state(now, degraded_review_retries=2), findings=[], proof_ok=True)
    assert result["terminal"] in ("two-stable", "two-stable [code-review-only]")
    assert result["state"]["degraded_review_retries"] == 0


def test_non_terminal_round_resets_to_zero():
    now = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)
    # structural-present verdict → not convergence-eligible → non-terminal → reset
    state = _state(now, degraded_review_retries=3, last_verdict="structural-present")
    real_finding = [{"source": "code-review", "file": "x.py", "line_range": [1, 2],
                     "summary": "issue", "verdict": "structural"}]
    result = _run(state, findings=real_finding, proof_ok=None)
    assert result["terminal"] is None
    assert result["state"]["degraded_review_retries"] == 0
