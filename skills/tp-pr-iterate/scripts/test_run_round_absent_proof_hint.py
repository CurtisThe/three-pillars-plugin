"""run_round.py — absent-proof ordering hint (Task 3.1).

An eligible round that reaches `not_converged_reason ==
"degraded-or-absent-proof-on-head"` (and does NOT converge) also carries a fixed
`not_converged_hint` telling the caller to post the head-bound proof comment BEFORE
this round, naming converge.py as the ordered finisher — so a mis-ordered call
self-explains. A converged round carries no such hint. Hermetic: inline state, no
review_proof_root (the cheap fail-closed path), no live gh.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
RUN_ROUND_PY = SCRIPTS_DIR / "run_round.py"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import review_proof  # noqa: E402


def _run(payload: dict):
    result = subprocess.run(
        [sys.executable, str(RUN_ROUND_PY)],
        input=json.dumps(payload).encode(), capture_output=True,
    )
    return result.returncode, json.loads(result.stdout.decode().strip())


def _minimal_state(last_verdict="minor-only") -> dict:
    now = datetime(2026, 7, 7, 12, 0, 0, tzinfo=timezone.utc)
    started = (now - timedelta(hours=1)).isoformat()
    return {
        "phase": "awaiting-copilot", "iteration": 1, "max_iterations": 8,
        "max_wall_clock_sec": 14400, "started_at": started, "transitions": [],
        "cumulative_diff_lines": 0, "original_diff_lines": 100,
        "consecutive_structural_rounds": 0, "last_loop_sha": None,
        "last_comment_seen_at": None, "last_verdict": last_verdict,
        "last_codereview_head_sha": "abc1234", "last_codereview_findings": [],
    }


def _config() -> dict:
    return {"review": {"expects_copilot": False},
            "ci": {"expects_github_checks": False}}


def test_absent_proof_eligible_round_carries_ordering_hint():
    """Eligible round, no proof on head → blocked with the converge.py ordering hint."""
    payload = {
        "state": _minimal_state(), "head_sha": "abc1234",
        "codereview_findings": [], "reviewed": None, "unresolved_actionable": 0,
        "ci_rollup": [], "config": _config(),
        "pr_url": "https://github.com/o/r/pull/1",
    }
    rc, env = _run(payload)
    assert rc == 0
    assert env["converged"] is False
    assert env.get("not_converged_reason") == "degraded-or-absent-proof-on-head"
    hint = env.get("not_converged_hint")
    assert hint, "expected a not_converged_hint on an absent-proof eligible round"
    assert "converge.py" in hint
    assert "before" in hint.lower()


def test_converged_round_has_no_hint(tmp_path):
    proof_root = tmp_path / "proof"
    review_proof.capture_proof(
        "base000", "abc1234", ["angle response"], root=proof_root,
        run_git=lambda a: (0, "3\t1\tf.py\n", ""))
    digest = review_proof.format_proof_digest({
        "base": "base000", "head": "abc1234", "files_changed": 3,
        "insertions": 5, "deletions": 1, "degraded": False, "reason": None})
    payload = {
        "state": _minimal_state(), "head_sha": "abc1234",
        "codereview_findings": [], "reviewed": None, "unresolved_actionable": 0,
        "ci_rollup": [], "config": _config(),
        "pr_url": "https://github.com/o/r/pull/1",
        "review_proof_root": str(proof_root),
        "posted_comments": [{"author": "tp-bot", "body": digest}],
        "self_login": "tp-bot",
    }
    rc, env = _run(payload)
    assert rc == 0
    assert env["converged"] is True
    assert "not_converged_hint" not in env
