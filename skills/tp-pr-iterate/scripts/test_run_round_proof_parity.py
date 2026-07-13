"""test_run_round_proof_parity.py — CLI ↔ in-process proof parity (B4).

The autonomous CLI path (run_round.py main) and the in-process loop (run_loop)
must BLOCK identically on an un-proofed convergence-eligible round. run_round.py is
NOT edited — parity is the assertion. Hermetic: stdin JSON to the CLI; injected
proof_ok_fn for the loop. No live gh/git.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUN_ROUND_PY = HERE / "run_round.py"
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import loop_driver  # noqa: E402

PR = "https://github.com/o/r/pull/1"
_CONFIG = {"review": {"expects_copilot": False}, "ci": {"expects_github_checks": False}}


def _run_cli(payload):
    result = subprocess.run(
        [sys.executable, str(RUN_ROUND_PY)],
        input=json.dumps(payload).encode(), capture_output=True,
    )
    try:
        env = json.loads(result.stdout.strip())
    except Exception:
        env = {"_stdout": result.stdout.decode(), "_stderr": result.stderr.decode()}
    return result.returncode, env


def _conv_state(tmp_path):
    now = datetime(2026, 6, 20, 12, 0, 0, tzinfo=timezone.utc)
    started = (now - timedelta(hours=1)).isoformat()
    state = {
        "phase": "awaiting-copilot", "iteration": 1, "max_iterations": 8,
        "max_wall_clock_sec": 14400, "started_at": started, "transitions": [],
        "cumulative_diff_lines": 0, "original_diff_lines": 100,
        "consecutive_structural_rounds": 0, "last_loop_sha": None,
        "last_comment_seen_at": None, "last_verdict": "minor-only",
        "last_codereview_head_sha": "abc1234", "last_codereview_findings": [],
    }
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(state), encoding="utf-8")
    return state_file


def test_cli_blocks_unproofed_convergence(tmp_path):
    """run_round.py main(): convergence-eligible + NO review_proof_root → blocked,
    proof_enforced=False, proof_ok=False."""
    state_file = _conv_state(tmp_path)
    payload = {
        "state_path": str(state_file),
        "head_sha": "abc1234",
        "codereview_findings": [],
        "reviewed": None,
        "unresolved_actionable": 0,
        "ci_rollup": [],
        "config": _CONFIG,
        "pr_url": PR,
        # NO review_proof_root → fail-closed on convergence-eligible round.
    }
    rc, env = _run_cli(payload)
    assert rc == 0, env
    assert env.get("terminal") == "blocked-no-independent-review", env
    assert env.get("converged") is False
    assert env.get("proof_ok") is False
    assert env.get("proof_enforced") is False


def test_inprocess_run_loop_blocks_same_input(monkeypatch):
    """The same logical convergence input through run_loop with proof_ok_fn→False →
    the SAME terminal as the CLI (parity)."""
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = {
        "phase": "fixing", "iteration": 0, "max_iterations": 8,
        "max_wall_clock_sec": 14400, "started_at": now.isoformat(),
        "last_verdict": None, "transitions": [], "cumulative_diff_lines": 0,
        "original_diff_lines": 100, "consecutive_structural_rounds": 0,
        "last_loop_sha": None, "last_comment_seen_at": None,
        "seen_thread_ids": [], "resolved_thread_ids": [], "termination_reason": None,
    }
    rounds = [
        {
            "new_comments": [{"id": 1}],
            "classified": [{"comment_id": "c1", "verdict": "structural",
                            "file": "f.py", "line_range": [1, 5]}],
            "codereview_findings": [], "copilot_threads": [],
            "head_sha": "abc1234", "commit_id": "abc1234",
        },
        {
            "new_comments": [],
            "classified": [{"comment_id": "c1", "verdict": "minor",
                            "file": "f.py", "line_range": [1, 5]}],
            "codereview_findings": [], "copilot_threads": [],
            "head_sha": "abc1234", "commit_id": "abc1234",
        },
    ]
    rounds_iter = iter(rounds)

    def poll_fn():
        r = next(rounds_iter)
        return (r["new_comments"], r["classified"], r["codereview_findings"],
                r["copilot_threads"], r["head_sha"], r["commit_id"])

    monkeypatch.setattr(loop_driver, "_ci_settled_on_head",
                        lambda *a, **kw: (True, None, [{"conclusion": "SUCCESS"}]))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", lambda *a, **kw: None)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    result = loop_driver.run_loop(
        design="d", pr_url=PR, state=state, config=_CONFIG,
        dry_run=True, poll_fn=poll_fn, fix_round_fn=None,
        sleep_fn=lambda s: None, now_fn=lambda: now,
        unresolved_actionable_fn=lambda u: 0, reviewed_fn=lambda u: False,
        codereview_fn=lambda effort, head_sha: [],
        proof_ok_fn=lambda _h: False,
    )
    assert result.get("phase") == "blocked-no-independent-review"
    assert result.get("termination_reason") != "two-stable"


def test_parity_under_cap():
    src = (HERE / "test_run_round_proof_parity.py").read_text(encoding="utf-8")
    lines = src.count("\n") + 1
    assert lines <= 500, f"file is {lines} lines (cap=500)"
    assert len(src) <= 50000
