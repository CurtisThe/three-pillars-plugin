"""CLI-boundary tests for run_round.py's posted-digest + unparseable convergence gate.

review-integrity-enforcement Task 2.3. NEW file (test_run_round_cli_proof.py is at the
soft-warn). Drives run_round.py via stdin JSON; feeds the posted digest through the
`posted_comments` seam; builds digest bodies with the REAL review_proof.format_proof_digest.

Every fixture uses a config WITHOUT approval_survives_safe_base_sync (carry OFF → pure
proof_comment_on_head, no live git). The cases that isolate the NEW run_round conjunct as
load-bearing pin `expects_copilot=true, reviewed=True`: loop_driver._independent_review_ran
already embeds `not is_degraded_review(...)` inside review_available, so on an
expects_copilot=false config a garbled angle is ALREADY blocked and the test would pass with
or without the new conjunct. With the Copilot arm driving ran=True, the new conjunct
(proof_ok) becomes the SOLE thing blocking convergence.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
RUN_ROUND_PY = SCRIPTS_DIR / "run_round.py"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import review_merge  # noqa: E402
import review_proof  # noqa: E402


def _run(payload: dict):
    result = subprocess.run(
        [sys.executable, str(RUN_ROUND_PY)],
        input=json.dumps(payload).encode(), capture_output=True,
    )
    try:
        env = json.loads(result.stdout.strip())
    except Exception:
        env = {"_stdout": result.stdout.decode(), "_stderr": result.stderr.decode()}
    return result.returncode, env


def _minimal_state(last_verdict="minor-only") -> dict:
    from datetime import datetime, timezone, timedelta
    now = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)
    started = (now - timedelta(hours=1)).isoformat()
    return {
        "phase": "awaiting-copilot", "iteration": 1, "max_iterations": 8,
        "max_wall_clock_sec": 14400, "started_at": started, "transitions": [],
        "cumulative_diff_lines": 0, "original_diff_lines": 100,
        "consecutive_structural_rounds": 0, "last_loop_sha": None,
        "last_comment_seen_at": None, "last_verdict": last_verdict,
        "last_codereview_head_sha": "abc1234", "last_codereview_findings": [],
    }


def _config(expects_copilot: bool) -> dict:
    # Carry OFF (no approval_survives_safe_base_sync); no GitHub CI so empty rollup settles.
    return {"review": {"expects_copilot": expects_copilot},
            "ci": {"expects_github_checks": False}}


def _digest(head="abc1234", *, degraded=False) -> str:
    if degraded:
        return review_proof.format_proof_digest({"degraded": True, "reason": "empty-diff"})
    return review_proof.format_proof_digest({
        "base": "base000", "head": head, "files_changed": 3,
        "insertions": 5, "deletions": 1, "degraded": False, "reason": None})


def _posted(digest, author="tp-bot") -> list:
    return [{"author": author, "body": digest}]


def _stage_artifact(tmp_path, head="abc1234"):
    """A present, non-degraded local proof artifact so the local arm is True — isolating
    the posted-digest / findings conjunct as the sole discriminator."""
    proof_root = tmp_path / "proof"
    review_proof.capture_proof(
        "base000", head, ["angle response"], root=proof_root,
        run_git=lambda args: (0, "3\t1\tf.py\n", ""))
    return proof_root


def _payload(tmp_path, *, expects_copilot, reviewed, findings, posted_comments,
             head="abc1234"):
    proof_root = _stage_artifact(tmp_path, head)
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(_minimal_state()), encoding="utf-8")
    return {
        "state_path": str(state_file),
        "head_sha": head,
        "codereview_findings": findings,
        "reviewed": reviewed,
        "unresolved_actionable": 0,
        "ci_rollup": [],
        "config": _config(expects_copilot),
        "pr_url": "https://github.com/o/r/pull/1",
        "review_proof_root": str(proof_root),
        "posted_comments": posted_comments,
        "self_login": "tp-bot",
    }


# ---------- Case 1: positive control (convergence preserved) ----------


def test_present_nondegraded_digest_clean_findings_converges(tmp_path):
    rc, env = _run(_payload(
        tmp_path, expects_copilot=False, reviewed=None,
        findings=[], posted_comments=_posted(_digest())))
    assert rc == 0
    assert env.get("converged") is True, env
    assert env.get("terminal") in ("two-stable", "two-stable [code-review-only]")
    assert env.get("convergence_proof_ok") is True


# ---------- Case 2: degraded digest on head blocks ----------


def test_degraded_digest_on_head_blocks(tmp_path):
    rc, env = _run(_payload(
        tmp_path, expects_copilot=True, reviewed=True,
        findings=[], posted_comments=_posted(_digest(degraded=True))))
    assert rc == 0
    assert env.get("terminal") == "blocked-no-independent-review", env
    assert env.get("converged") is False
    assert env.get("not_converged_reason") == "degraded-or-absent-proof-on-head"


# ---------- Case 3: absent digest blocks ----------


def test_absent_digest_blocks(tmp_path):
    rc, env = _run(_payload(
        tmp_path, expects_copilot=True, reviewed=True,
        findings=[], posted_comments=[]))
    assert rc == 0
    assert env.get("terminal") == "blocked-no-independent-review", env
    assert env.get("converged") is False
    assert env.get("not_converged_reason") == "degraded-or-absent-proof-on-head"


# ---------- Case 4: UNPARSEABLE angle + non-degraded digest still blocks ----------


def test_unparseable_angle_with_nondegraded_digest_blocks(tmp_path):
    """The #104/#117-defeating core: capture_proof produces a NON-degraded digest for a
    garbled angle, so the posted-digest conjunct alone would PASS. The independent
    is_degraded_review(findings) conjunct forces the block. Pinned expects_copilot=true +
    reviewed=True so the Copilot arm drives ran=True and this conjunct is the SOLE blocker
    (drop it → this round converges)."""
    garbled = review_merge.merge_codereview_angles(["not-json garbage"])
    assert review_merge.is_degraded_review(garbled) is True
    rc, env = _run(_payload(
        tmp_path, expects_copilot=True, reviewed=True,
        findings=garbled, posted_comments=_posted(_digest())))  # digest NON-degraded
    assert rc == 0
    assert env.get("terminal") == "blocked-no-independent-review", env
    assert env.get("converged") is False
    assert env.get("not_converged_reason") == "unparseable-review-angle"


def test_no_angles_sentinel_with_nondegraded_digest_blocks(tmp_path):
    """merge_codereview_angles([]) (NO-ANGLES) is caught by the same findings conjunct."""
    no_angles = review_merge.merge_codereview_angles([])
    rc, env = _run(_payload(
        tmp_path, expects_copilot=True, reviewed=True,
        findings=no_angles, posted_comments=_posted(_digest())))
    assert rc == 0
    assert env.get("terminal") == "blocked-no-independent-review", env
    assert env.get("not_converged_reason") == "unparseable-review-angle"


# ---------- Case 5: #117 Copilot-arm bypass closed ----------


def test_copilot_reviewed_over_degraded_digest_still_blocks(tmp_path):
    """#117 shape: Copilot reviewed successfully (reviewed=True, expects_copilot=true) but
    the on-head signal is DEGRADED (degraded digest AND an unparseable angle). Narration /
    the Copilot arm cannot override the fail-closed signal — still blocked."""
    garbled = review_merge.merge_codereview_angles(["not-json garbage"])
    rc, env = _run(_payload(
        tmp_path, expects_copilot=True, reviewed=True,
        findings=garbled, posted_comments=_posted(_digest(degraded=True))))
    assert rc == 0
    assert env.get("terminal") == "blocked-no-independent-review", env
    assert env.get("converged") is False
    assert env.get("convergence_proof_ok") is False
