"""test_run_round_proof_parity.py — CLI proof blocking (B4).

The autonomous CLI path (run_round.py main) must BLOCK on an un-proofed
convergence-eligible round. The in-process loop twin was deleted with the loop
(iterate-convergence-budget Task 3.1). Hermetic: stdin JSON to the CLI. No live gh/git.
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
    # A fresh started_at: run_round.py's round_budget.tick checks the wall clock
    # against the real now (iterate-convergence-budget A11).
    now = datetime.now(tz=timezone.utc)
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


def test_parity_under_cap():
    src = (HERE / "test_run_round_proof_parity.py").read_text(encoding="utf-8")
    lines = src.count("\n") + 1
    assert lines <= 500, f"file is {lines} lines (cap=500)"
    assert len(src) <= 50000
