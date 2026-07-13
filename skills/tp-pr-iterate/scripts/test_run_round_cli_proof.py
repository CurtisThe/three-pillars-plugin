"""Tests for run_round.py CLI proof-of-review enforcement (Task 3.1).

Split from test_run_round_cli.py (codereview-proof-of-review design, Phase 3):
covers the new review_proof_root / review_base / proof_enforced contract.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent
RUN_ROUND_PY = SCRIPTS_DIR / "run_round.py"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import review_proof  # noqa: E402


def _run(payload: dict, cwd=None):
    """Invoke run_round.py with payload as stdin JSON.  Returns (returncode, envelope).

    cwd, when given, sets the subprocess working directory so the CLI's live-git
    re-derivation (resolve_numstat, which uses real git with no injectable shim)
    resolves against a specific real repo.  Default None → inherit (unchanged).
    """
    stdin_bytes = json.dumps(payload).encode()
    result = subprocess.run(
        [sys.executable, str(RUN_ROUND_PY)],
        input=stdin_bytes,
        capture_output=True,
        cwd=str(cwd) if cwd is not None else None,
    )
    try:
        envelope = json.loads(result.stdout.strip())
    except Exception:
        envelope = {"_raw_stdout": result.stdout.decode(), "_stderr": result.stderr.decode()}
    return result.returncode, envelope


def _minimal_state(last_verdict="minor-only") -> dict:
    from datetime import datetime, timezone, timedelta
    now = datetime(2026, 6, 20, 12, 0, 0, tzinfo=timezone.utc)
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
        "last_codereview_head_sha": "abc1234",
        "last_codereview_findings": [],
    }


def _clean_config() -> dict:
    return {"review": {"expects_copilot": False}, "ci": {"expects_github_checks": False}}


def _stage_proof(tmp_path, head="abc1234", base="base000", numstat="3\t1\tf.py\n"):
    """Stage a proof artifact. Returns (proof_root, base)."""
    proof_root = tmp_path / "proof"
    review_proof.capture_proof(
        base, head, ["resp"],
        root=proof_root,
        run_git=lambda args: (0, numstat, ""),
    )
    return proof_root, base


def _posted_digest(head="abc1234", author="tp-bot") -> list:
    """A non-degraded trusted proof digest on `head`, built via the REAL formatter."""
    digest = review_proof.format_proof_digest({
        "base": "base000", "head": head, "files_changed": 3,
        "insertions": 5, "deletions": 1, "degraded": False, "reason": None,
    })
    return [{"author": author, "body": digest}]


def _conv_payload(state_file, proof_root, base=None, head="abc1234") -> dict:
    payload = {
        "state_path": str(state_file),
        "head_sha": head,
        "codereview_findings": [],
        "reviewed": None,
        "unresolved_actionable": 0,
        "ci_rollup": [],
        "config": _clean_config(),
        "pr_url": "https://github.com/o/r/pull/1",
        "review_proof_root": str(proof_root),
        # review-integrity-enforcement: convergence now ALSO requires a non-degraded
        # trusted proof digest on head. Feed it hermetically via the posted_comments seam
        # (carry-OFF config → pure proof_comment_on_head, no live gh). Blocking fixtures
        # (missing/degraded/live-empty artifact) fail-closed on the local arm before this
        # is consulted, so it does not weaken them.
        "posted_comments": _posted_digest(head=head),
        "self_login": "tp-bot",
    }
    if base is not None:
        payload["review_base"] = base
    return payload


def _real_git_repo(tmp_path):
    """Create a real one-commit git repo; return (repo_path, head_sha).

    Used by the branch-(d) override test: the CLI's ground-truth re-derivation
    runs REAL git (no injectable shim) against the process cwd, so faithfully
    testing it requires a real repo rather than a stubbed run_git.
    """
    repo = tmp_path / "repo"
    repo.mkdir()

    def g(*args):
        subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, check=True,
        )

    g("init", "-q")
    g("config", "user.email", "t@example.com")
    g("config", "user.name", "Test")
    (repo / "f.py").write_text("x = 1\n", encoding="utf-8")
    g("add", "-A")
    g("commit", "-q", "-m", "c1")
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return repo, sha


# ---------- Task 3.1: CLI proof branches ----------


def test_cli_proof_present_nonempty_converges(tmp_path):
    """review_proof_root present + artifact present-nonempty → converged=True."""
    proof_root, _base = _stage_proof(tmp_path)
    state = _minimal_state()
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(state), encoding="utf-8")
    # No review_base: ground_ok defaults to True (artifact-only check)
    rc, env = _run(_conv_payload(state_file, proof_root))
    assert rc == 0
    assert env.get("converged") is True, f"proof present must allow convergence; {env}"
    assert env.get("proof_ok") is True


def test_cli_proof_missing_blocks(tmp_path):
    """review_proof_root present + NO artifact → blocked-no-independent-review."""
    proof_root = tmp_path / "proof"  # not populated
    state = _minimal_state()
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(state), encoding="utf-8")
    rc, env = _run(_conv_payload(state_file, proof_root))
    assert rc == 0
    assert env.get("terminal") == "blocked-no-independent-review"
    assert env.get("converged") is False
    assert env.get("proof_ok") is False


def test_cli_proof_degraded_artifact_blocks(tmp_path):
    """review_proof_root present + degraded artifact (empty-diff) → blocked."""
    # Stage a degraded artifact: empty diff numstat
    proof_root = tmp_path / "proof"
    review_proof.capture_proof(
        "base000", "abc1234", [],
        root=proof_root,
        run_git=lambda args: (0, "", ""),  # empty diff → degraded
    )
    state = _minimal_state()
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(state), encoding="utf-8")
    rc, env = _run(_conv_payload(state_file, proof_root))  # no review_base
    assert rc == 0
    assert env.get("terminal") == "blocked-no-independent-review", (
        f"degraded artifact must block convergence; {env}"
    )
    assert env.get("converged") is False


def test_cli_proof_omitted_convergence_eligible_fails_closed(tmp_path):
    """review_proof_root omitted on convergence-eligible round → blocked + proof_enforced=False."""
    state = _minimal_state()
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(state), encoding="utf-8")
    payload = {
        "state_path": str(state_file),
        "head_sha": "abc1234",
        "codereview_findings": [],
        "reviewed": None,
        "unresolved_actionable": 0,
        "ci_rollup": [],
        "config": _clean_config(),
        "pr_url": "https://github.com/o/r/pull/1",
        # review_proof_root deliberately absent
    }
    rc, env = _run(payload)
    assert rc == 0
    assert env.get("terminal") == "blocked-no-independent-review", (
        f"omitted root on convergence-eligible round must fail-closed; got {env}"
    )
    assert env.get("proof_enforced") is False, (
        "proof_enforced=False must appear in envelope when un-proofed convergence blocked"
    )
    assert env.get("converged") is False


def test_cli_proof_omitted_non_convergence_unaffected(tmp_path):
    """review_proof_root omitted on non-convergence round → no spurious block."""
    state = _minimal_state(last_verdict="structural-present")
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(state), encoding="utf-8")
    payload = {
        "state_path": str(state_file),
        "head_sha": "abc1234",
        "codereview_findings": [
            {"source": "code-review", "file": "x.py", "line_range": [1, 2],
             "summary": "issue", "verdict": "structural"},
        ],
        "reviewed": None,
        "unresolved_actionable": 1,
        "ci_rollup": [],
        "config": _clean_config(),
        "pr_url": "https://github.com/o/r/pull/1",
    }
    rc, env = _run(payload)
    assert rc == 0
    assert env.get("terminal") is None, (
        f"non-convergence round must not be spuriously blocked; got {env}"
    )
    assert "proof_enforced" not in env


def test_cli_proof_no_review_base_uses_artifact_only(tmp_path):
    """When review_base is absent, ground_ok defaults to True (artifact-only check).

    This verifies the 'independent re-derivation branch' behavior:
    - When review_base is provided: live git diff is run for independent verification.
    - When review_base is absent: only the artifact is checked (ground_ok=True).
    With a present artifact + no review_base: converges.
    """
    proof_root = tmp_path / "proof"
    review_proof.capture_proof(
        "base000", "abc1234", ["resp"],
        root=proof_root,
        run_git=lambda args: (0, "3\t1\tf.py\n", ""),
    )
    state = _minimal_state()
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(state), encoding="utf-8")
    # No review_base → ground_ok=True → artifact-only check → converges
    rc, env = _run(_conv_payload(state_file, proof_root))
    assert rc == 0
    assert env.get("converged") is True, (
        f"artifact present + no review_base (ground_ok=True) must converge; {env}"
    )
    assert env.get("proof_ok") is True


def test_cli_proof_live_empty_overrides_nonempty_artifact_blocks(tmp_path):
    """Branch (d) — independent re-derivation OVERRIDES a forged/stale non-empty artifact.

    plan.md:81: present artifact + a review_base whose LIVE numstat is empty → blocked.
    This is the provenance-vs-authenticity guarantee actually biting.  The artifact meta
    claims a non-empty diff (forged via the capture shim), but the CLI re-derives
    numstat(base...head) from REAL git — base==head → empty → degraded → ground_ok=False
    → proof_ok=False → block.  Without the live veto (no review_base) this same artifact
    converges (test_cli_proof_no_review_base_uses_artifact_only), so the override is
    load-bearing, not redundant: drop the re-derivation and this test goes green-converged.
    """
    repo, sha = _real_git_repo(tmp_path)

    # Forge a NON-EMPTY artifact bound to head=sha (capture shim lies: 3 ins / 1 del / f.py).
    proof_root = tmp_path / "proof"
    review_proof.capture_proof(
        sha, sha, ["resp"],
        root=proof_root,
        run_git=lambda args: (0, "3\t1\tf.py\n", ""),
    )
    # Precondition: the artifact ALONE is present-and-nonempty, so the block below can
    # only be the live-git ground-truth veto — not a weak or absent artifact.
    assert review_proof.proof_present_and_nonempty(sha, root=proof_root) is True

    state = _minimal_state()
    state["last_codereview_head_sha"] = sha  # keep head-match → round stays convergence-eligible
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(state), encoding="utf-8")

    # review_base == head == sha → live `git diff --numstat sha...sha` is empty (degraded).
    rc, env = _run(_conv_payload(state_file, proof_root, base=sha, head=sha), cwd=repo)
    assert rc == 0
    assert env.get("terminal") == "blocked-no-independent-review", (
        f"live-empty re-derivation must override a non-empty artifact and block; got {env}"
    )
    assert env.get("converged") is False
    assert env.get("proof_ok") is False


# ---------- CLI eligibility predicate conjuncts (run_round.py:248-252) ----------
# These pin that `eligible` is the FULL conjunction (minor-only AND CI-all-success AND
# zero unresolved-actionable). The existing omitted-root tests only vary last_verdict,
# so mutating `eligible` down to `last_verdict=='minor-only'` alone survives them.
# `proof_enforced` appears in the envelope ONLY on the eligible+omitted-root branch, so
# its ABSENCE is the exact discriminator: present under the mutant, absent when correct.


def test_cli_proof_omitted_minor_only_ci_failed_not_eligible(tmp_path):
    """Omitted root + minor-only but CI FAILED → not convergence-eligible → no proof block.

    Pins the `_ci_all_success` conjunct. Reducing `eligible` to last_verdict alone would
    wrongly enforce proof here (proof_enforced=False); the live conjunct keeps proof_ok=None
    because CI is settled-failed, so the proof gate must not fire on this round.
    """
    state = _minimal_state()  # last_verdict='minor-only'
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(state), encoding="utf-8")
    payload = {
        "state_path": str(state_file),
        "head_sha": "abc1234",
        "codereview_findings": [],
        "reviewed": None,
        "unresolved_actionable": 0,
        "ci_rollup": [{"conclusion": "FAILURE"}],
        # expects_github_checks=True so a FAILURE rollup makes _ci_all_success() False
        "config": {"review": {"expects_copilot": False}, "ci": {"expects_github_checks": True}},
        "pr_url": "https://github.com/o/r/pull/1",
        # review_proof_root deliberately absent
    }
    rc, env = _run(payload)
    assert rc == 0
    assert "proof_enforced" not in env, (
        f"minor-only but CI-failed is NOT convergence-eligible — proof must not be enforced; got {env}"
    )


def test_cli_proof_omitted_minor_only_unresolved_not_eligible(tmp_path):
    """Omitted root + minor-only but unresolved_actionable>0 → not eligible → no proof block.

    Pins the `unresolved_actionable == 0` conjunct. CI is vacuously all-success here
    (empty rollup + expects_github_checks=false), so the ONLY thing keeping the round
    non-eligible is the open actionable thread. Reducing `eligible` to last_verdict alone
    would wrongly enforce proof (proof_enforced=False); correct code keeps proof_ok=None.
    """
    state = _minimal_state()  # last_verdict='minor-only'
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(state), encoding="utf-8")
    payload = {
        "state_path": str(state_file),
        "head_sha": "abc1234",
        "codereview_findings": [],
        "reviewed": None,
        "unresolved_actionable": 1,
        "ci_rollup": [],
        "config": _clean_config(),
        "pr_url": "https://github.com/o/r/pull/1",
        # review_proof_root deliberately absent
    }
    rc, env = _run(payload)
    assert rc == 0
    assert "proof_enforced" not in env, (
        f"minor-only but unresolved_actionable>0 is NOT convergence-eligible — proof must not be enforced; got {env}"
    )
