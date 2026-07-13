"""Tests for the run_round.py CLI wrapper.

Verifies the stdin-JSON → stdout-envelope → exit-code contract:
  0 — ok
  2 — escalate (any wrapper failure)
  (exit 1 is NEVER used)

Mirrors the test pattern in test_run_tier_3_5.py (tp-run-full-design).
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent
RUN_ROUND_PY = SCRIPTS_DIR / "run_round.py"


def _run(payload: dict, *, state_path: Path | None = None, extra_env=None):
    """Invoke run_round.py with payload as stdin JSON.

    Returns (returncode, envelope_dict).
    """
    stdin_bytes = json.dumps(payload).encode()
    result = subprocess.run(
        [sys.executable, str(RUN_ROUND_PY)],
        input=stdin_bytes,
        capture_output=True,
    )
    try:
        envelope = json.loads(result.stdout.strip())
    except Exception:
        envelope = {"_raw_stdout": result.stdout.decode(), "_stderr": result.stderr.decode()}
    return result.returncode, envelope


def _minimal_state(last_verdict: str = "minor-only") -> dict:
    """Minimal valid iterate-state for testing."""
    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)
    started = (now - timedelta(hours=1)).isoformat()
    return {
        "phase": "awaiting-copilot",
        "iteration": 1,
        "max_iterations": 8,
        "max_wall_clock_sec": 14400,
        "started_at": started,
        "transitions": [],
        "cumulative_diff_lines": 0,
        "original_diff_lines": 100,
        "consecutive_structural_rounds": 0,
        "last_loop_sha": None,
        "last_comment_seen_at": None,
        "last_verdict": last_verdict,
    }


def _clean_config() -> dict:
    """Config that makes an empty ci_rollup pass _ci_all_success."""
    return {"review": {"expects_copilot": False}, "ci": {"expects_github_checks": False}}


# ---------- State-path mode ----------


def test_run_round_cli_ok_with_state_path(tmp_path):
    """state_path mode: wrapper reads state, runs run_round, writes updated state,
    emits single-line JSON envelope with status=ok, exit 0."""
    state = _minimal_state()
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(state))

    payload = {
        "state_path": str(state_file),
        "head_sha": "abc1234",
        "codereview_findings": [],
        "reviewed": None,
        "unresolved_actionable": 1,  # prevent convergence
        "ci_rollup": [],
        "config": _clean_config(),
        "pr_url": "https://github.com/o/r/pull/1",
    }

    rc, env = _run(payload)

    assert rc == 0, f"expected exit 0, got {rc}; envelope={env}"
    assert env.get("status") == "ok", f"expected status=ok; got {env}"
    assert env.get("state_written") is True
    assert "action" in env
    assert "terminal" in env
    assert "converged" in env
    assert "head_sha" in env

    # Verify state was actually written back.
    written = json.loads(state_file.read_text(encoding="utf-8"))
    assert written != state, "state file must be updated after run_round"


def test_run_round_cli_blocked_no_independent_review(tmp_path):
    """Degraded findings + expects_copilot=False + minor-only + unresolved=0
    → terminal=blocked-no-independent-review, converged=false."""
    import sys
    sys.path.insert(0, str(SCRIPTS_DIR))
    import review_merge as rm

    degraded = rm.merge_codereview_angles([])
    state = _minimal_state()
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(state))

    payload = {
        "state_path": str(state_file),
        "head_sha": "abc1234",
        "codereview_findings": degraded,
        "reviewed": None,
        "unresolved_actionable": 0,
        "ci_rollup": [],
        "config": _clean_config(),
        "pr_url": "https://github.com/o/r/pull/1",
    }

    rc, env = _run(payload)

    assert rc == 0, f"expected exit 0, got {rc}; envelope={env}"
    assert env.get("terminal") == "blocked-no-independent-review"
    assert env.get("converged") is False


def test_run_round_cli_two_stable_converged(tmp_path):
    """Real-clean findings, cache head matches, expects_copilot=False, proof artifact present →
    terminal in two-stable variants, converged=true.

    Updated by codereview-proof-of-review: convergence now requires a proof artifact.
    We stage one via capture_proof into a tmp root, then pass review_proof_root + review_base.
    """
    import sys
    sys.path.insert(0, str(SCRIPTS_DIR))
    import review_proof

    # Stage a real proof artifact
    proof_root = tmp_path / "proof"
    review_proof.capture_proof(
        "base000", "abc1234",
        ["angle response"],
        root=proof_root,
        run_git=lambda args: (0, "3\t1\tfile.py\n", ""),
    )

    state = _minimal_state()
    # Pre-seed the cache so cached_head_sha == head_sha in run_round
    state["last_codereview_head_sha"] = "abc1234"
    state["last_codereview_findings"] = []
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(state))

    payload = {
        "state_path": str(state_file),
        "head_sha": "abc1234",
        "codereview_findings": [],  # real-clean
        "reviewed": None,
        "unresolved_actionable": 0,
        "ci_rollup": [],
        "config": _clean_config(),
        "pr_url": "https://github.com/o/r/pull/1",
        "review_proof_root": str(proof_root),
        # review_base intentionally omitted — ground_ok defaults to True in this test
        # (live git call not needed to verify the artifact-present branch).
        # review-integrity-enforcement: convergence now also requires a non-degraded
        # trusted proof digest on head — feed it hermetically (carry-OFF config).
        "posted_comments": [{"author": "tp-bot", "body": review_proof.format_proof_digest({
            "base": "base000", "head": "abc1234", "files_changed": 3,
            "insertions": 5, "deletions": 1, "degraded": False, "reason": None})}],
        "self_login": "tp-bot",
    }

    rc, env = _run(payload)

    assert rc == 0
    assert env.get("terminal") in ("two-stable", "two-stable [code-review-only]"), (
        f"proof artifact present must allow convergence; got {env}"
    )
    assert env.get("converged") is True


# ---------- Inline-state mode ----------


def test_run_round_cli_inline_state_returns_updated_state():
    """inline state mode (no state_path) returns updated state in envelope."""
    state = _minimal_state()
    payload = {
        "state": state,
        "head_sha": "abc1234",
        "codereview_findings": [],
        "reviewed": None,
        "unresolved_actionable": 1,
        "ci_rollup": [],
        "config": _clean_config(),
        "pr_url": "https://github.com/o/r/pull/1",
    }

    rc, env = _run(payload)

    assert rc == 0, f"expected exit 0; got {rc}: {env}"
    assert env.get("status") == "ok"
    assert "state" in env, "inline-state mode must return updated state in envelope"
    assert env.get("state_written") is False  # no file written


def test_run_round_cli_state_written_false_inline():
    """state_written is False when running in inline-state mode (no file)."""
    state = _minimal_state()
    payload = {"state": state, "head_sha": "h", "codereview_findings": [],
               "unresolved_actionable": 1, "ci_rollup": [],
               "config": _clean_config()}
    rc, env = _run(payload)
    assert rc == 0
    assert env.get("state_written") is False


# ---------- Error paths (all escalate, exit 2) ----------


def test_run_round_cli_malformed_stdin():
    """Malformed JSON stdin → escalate, exit 2."""
    result = subprocess.run(
        [sys.executable, str(RUN_ROUND_PY)],
        input=b"not valid json",
        capture_output=True,
    )
    assert result.returncode == 2
    env = json.loads(result.stdout.strip())
    assert env.get("status") == "escalate"


def test_run_round_cli_missing_state_and_state_path():
    """Neither state nor state_path → escalate, exit 2."""
    payload = {"head_sha": "abc", "codereview_findings": []}
    rc, env = _run(payload)
    assert rc == 2
    assert env.get("status") == "escalate"


def test_run_round_cli_unreadable_state_path(tmp_path):
    """state_path points to a non-existent file → escalate, exit 2."""
    payload = {
        "state_path": str(tmp_path / "does_not_exist.json"),
        "head_sha": "abc",
        "codereview_findings": [],
    }
    rc, env = _run(payload)
    assert rc == 2
    assert env.get("status") == "escalate"


def test_run_round_cli_unwritable_state_path(tmp_path):
    """state_path exists but is not writable → escalate, exit 2."""
    import os

    state = _minimal_state()
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(state))
    # Make the file read-only.
    state_file.chmod(0o444)

    payload = {
        "state_path": str(state_file),
        "head_sha": "abc1234",
        "codereview_findings": [],
        "reviewed": None,
        "unresolved_actionable": 0,
        "ci_rollup": [],
        "config": _clean_config(),
        "pr_url": "https://github.com/o/r/pull/1",
    }

    rc, env = _run(payload)

    # Restore permissions so tmp_path cleanup works.
    state_file.chmod(0o644)

    assert rc == 2, f"expected exit 2 on write failure; got {rc}: {env}"
    assert env.get("status") == "escalate"


def test_run_round_cli_exit_1_never_used(tmp_path):
    """Confirm exit 1 is never returned — the wrapper only uses 0 and 2."""
    # We can check this by running a case that would be retry in run_tier_3_5 but
    # is escalate here (non-existent state path).
    missing = tmp_path / "subdir_that_does_not_exist" / "x.json"
    payload = {"state_path": str(missing), "head_sha": "h"}
    rc, env = _run(payload)
    assert rc != 1, "exit 1 must never be used by run_round.py"
    assert rc in (0, 2)


# ---------- C1: no anthropic import / no claude subprocess ----------


def test_run_round_cli_c1_no_anthropic():
    """C1: run_round.py must not import anthropic (ast-level check)."""
    import ast
    src = RUN_ROUND_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else ([node.module] if node.module else [])
            )
            for name in names:
                assert "anthropic" not in (name or ""), (
                    f"run_round.py must not import anthropic (C1); found: {name}"
                )


def test_run_round_cli_c1_no_claude_subprocess():
    """C1: run_round.py must not spawn a claude subprocess."""
    import ast
    src = RUN_ROUND_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # Detect subprocess.run(["claude", ...]) or similar
            func_str = ast.unparse(node) if hasattr(ast, "unparse") else ""
            if "claude" in func_str and "subprocess" in func_str:
                pytest.fail(
                    f"run_round.py must not spawn claude subprocess (C1): {func_str}"
                )
            # Check list literals with "claude" as first arg
            for arg in node.args:
                if isinstance(arg, ast.List):
                    elts = arg.elts
                    if elts and isinstance(elts[0], ast.Constant) and elts[0].value == "claude":
                        pytest.fail(
                            "run_round.py must not spawn ['claude', ...] subprocess (C1)"
                        )


# ---------- F-P1: config-absent behavior + expects_copilot=false convergence ----------


def test_run_round_cli_expects_copilot_false_config_reaches_code_review_only(tmp_path):
    """F-P1: a repo with review.expects_copilot=false MUST converge to
    'two-stable [code-review-only]' when passed an explicit config + proof artifact.

    Updated by codereview-proof-of-review: convergence now requires a proof artifact.
    We stage one and pass review_proof_root + review_base. (F-P1)"""
    import sys
    sys.path.insert(0, str(SCRIPTS_DIR))
    import review_proof

    # Stage a real proof artifact
    proof_root = tmp_path / "proof"
    review_proof.capture_proof(
        "base001", "abc1234",
        ["angle resp"],
        root=proof_root,
        run_git=lambda args: (0, "5\t2\tfile.py\n", ""),
    )

    state = _minimal_state()
    # Pre-seed the cache so cached_head_sha == head_sha
    state["last_codereview_head_sha"] = "abc1234"
    state["last_codereview_findings"] = []
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(state))

    payload = {
        "state_path": str(state_file),
        "head_sha": "abc1234",
        "codereview_findings": [],  # real-clean
        "reviewed": None,           # Copilot never reviewed (False/None)
        "unresolved_actionable": 0,
        "ci_rollup": [],
        # Explicit config: Copilot NOT expected, no GitHub CI
        "config": {"review": {"expects_copilot": False}, "ci": {"expects_github_checks": False}},
        "pr_url": "https://github.com/o/r/pull/1",
        "review_proof_root": str(proof_root),
        # review_base intentionally omitted — ground_ok defaults to True in this test.
        # review-integrity-enforcement: convergence now also requires a non-degraded
        # trusted proof digest on head — feed it hermetically (carry-OFF config).
        "posted_comments": [{"author": "tp-bot", "body": review_proof.format_proof_digest({
            "base": "base001", "head": "abc1234", "files_changed": 5,
            "insertions": 2, "deletions": 0, "degraded": False, "reason": None})}],
        "self_login": "tp-bot",
    }

    rc, env = _run(payload)

    assert rc == 0, f"expected exit 0; got {rc}: {env}"
    assert env.get("terminal") in ("two-stable", "two-stable [code-review-only]"), (
        f"expects_copilot=False with clean findings + proof must converge; "
        f"got terminal={env.get('terminal')}"
    )
    assert env.get("converged") is True, (
        "expects_copilot=False convergence must set converged=True"
    )


def test_run_round_cli_absent_config_defaults_to_expects_copilot_true(tmp_path):
    """F-P1: when 'config' key is ABSENT from stdin, the wrapper reads .three-pillars/config.json
    from cwd. If that file is also absent, it falls back to config=None (expects_copilot=True,
    expects_github_checks=True). With those defaults + unresolved_actionable=0 + real-clean
    findings + NO 'reviewed' signal, the loop does NOT converge (copilot conjunct required).

    This proves the absent-config behavior is fail-closed (not silently broken), not that
    it reaches code-review-only. A repo that relies on expects_copilot=false MUST pass config.
    (F-P1)"""
    state = _minimal_state()
    # Pre-seed the cache so cached_head_sha == head_sha
    state["last_codereview_head_sha"] = "abc1234"
    state["last_codereview_findings"] = []
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(state))

    # No 'config' key in payload → wrapper falls back to cwd .three-pillars/config.json
    # (which doesn't exist in tmp_path) → config=None → expects_copilot=True (default).
    # With reviewed=None and expects_copilot=True, the Copilot conjunct fails → no convergence.
    payload = {
        "state_path": str(state_file),
        "head_sha": "abc1234",
        "codereview_findings": [],  # real-clean
        "reviewed": None,           # Copilot NOT reviewed
        "unresolved_actionable": 0,
        "ci_rollup": [],
        # 'config' key deliberately ABSENT (not the same as config=None)
        "pr_url": "https://github.com/o/r/pull/1",
    }

    import os
    orig_cwd = os.getcwd()
    try:
        # Run from tmp_path where there is no .three-pillars/config.json
        os.chdir(tmp_path)
        rc, env = _run(payload)
    finally:
        os.chdir(orig_cwd)

    assert rc == 0, f"expected exit 0; got {rc}: {env}"
    # With absent config (defaults to expects_copilot=True) and reviewed=None,
    # convergence must NOT happen — the Copilot conjunct is required but unmet.
    assert env.get("terminal") not in ("two-stable", "two-stable [code-review-only]"), (
        "absent config must NOT silently converge code-review-only "
        f"(defaults to expects_copilot=True); terminal={env.get('terminal')}"
    )

