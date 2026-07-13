"""test_convergence_gate_hermetic.py — the #117 harness, on LIVE code.

Exercises the REAL stack end-to-end (no mocks of the units under test): real
review_merge.merge_codereview_angles, real review_proof.capture_proof +
format_proof_digest, real convergence_proof.resolve_convergence_proof_ok +
non_degraded_proof_on_head, real loop_driver.run_round. ONLY the outermost comment-fetch
seam (comments_fn) is injected. This is the class of test that would have caught #117: a
degraded/UNPARSEABLE final-head review CANNOT emit convergence.

All cases use a config WITHOUT approval_survives_safe_base_sync (carry OFF → no live git).
The cases that isolate the NEW run_round conjunct pin expects_copilot=true + reviewed=True
so the Copilot arm drives ran=True and the proof conjunct is the SOLE blocker (per the
audit: loop_driver._independent_review_ran already embeds is_degraded_review in
review_available, so an expects_copilot=false garbled angle is already blocked and would
not prove the new conjunct).
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
_SHARED = HERE.parent.parent / "_shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import convergence_proof  # noqa: E402
import loop_driver  # noqa: E402
import review_merge  # noqa: E402
import review_proof  # noqa: E402

PR = "https://github.com/o/r/pull/1"
HEAD = "abc1234deadbeefcafe0"
BASE = "base000"
AUTHOR = "tp-bot"


def _cfg(expects_copilot: bool) -> dict:
    return {"review": {"expects_copilot": expects_copilot},
            "ci": {"expects_github_checks": False}}


def _state():
    now = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)
    return {
        "phase": "awaiting-copilot", "iteration": 1, "max_iterations": 8,
        "max_wall_clock_sec": 14400, "started_at": (now - timedelta(hours=1)).isoformat(),
        "transitions": [], "cumulative_diff_lines": 0, "original_diff_lines": 100,
        "consecutive_structural_rounds": 0, "last_loop_sha": None,
        "last_comment_seen_at": None, "last_verdict": "minor-only",
        "last_codereview_head_sha": HEAD, "last_codereview_findings": [],
    }


def _comment(digest, author=AUTHOR):
    return [{"author": author, "body": digest}]


def _stage_local_artifact(tmp_path):
    """Real capture_proof — a present, non-degraded local artifact for HEAD."""
    proof_root = tmp_path / "proof"
    review_proof.capture_proof(
        BASE, HEAD, ["real angle response"], root=proof_root,
        run_git=lambda a: (0, "3\t1\tf.py\n", ""))
    return review_proof.proof_present_and_nonempty(HEAD, root=proof_root)


def _resolve(local_ok, *, findings, comments):
    """Fold proof_ok EXACTLY as run_round.py's CLI does (real convergence_proof)."""
    return convergence_proof.resolve_convergence_proof_ok(
        local_ok, eligible=True, pr_url=PR, head_sha=HEAD,
        codereview_findings=findings, config=None,
        comments_fn=(lambda _u: comments), self_login_fn=lambda: AUTHOR)


def _run(*, expects_copilot, reviewed, findings, proof_ok):
    return loop_driver.run_round(
        _state(), head_sha=HEAD, codereview_findings=findings, reviewed=reviewed,
        unresolved_actionable=0, ci_rollup=[], config=_cfg(expects_copilot),
        now=datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc),
        pr_url=PR, label_fn=lambda *a: None, unlabel_fn=lambda *a: None,
        proof_ok=proof_ok)


# ================= convergence REFUSED =================


def test_no_angles_plus_degraded_digest_blocks(tmp_path):
    """Case 1 — degraded angle output (real no-angles sentinel) + a ⚠️ DEGRADED posted
    digest → blocked."""
    local_ok = _stage_local_artifact(tmp_path)
    findings = review_merge.merge_codereview_angles([])  # real NO-ANGLES sentinel
    degraded_digest = review_proof.format_proof_digest({"degraded": True, "reason": "empty-diff"})
    proof_ok, reason = _resolve(local_ok, findings=findings, comments=_comment(degraded_digest))
    assert proof_ok is False
    result = _run(expects_copilot=True, reviewed=True, findings=findings, proof_ok=proof_ok)
    assert result["terminal"] == "blocked-no-independent-review"


def test_unparseable_angle_with_capture_derived_nondegraded_digest_blocks(tmp_path):
    """Case 2 — the load-bearing #117 core. The posted digest is DERIVED from a REAL
    capture_proof over a non-empty numstat, so it is genuinely NON-degraded (capture_proof
    sees only numstat + angle_count, never the garbled content). non_degraded_proof_on_head
    therefore returns True; the round is blocked ONLY by the is_degraded_review(findings)
    conjunct. Drop the conjunct → this converges (the pre-fix hole)."""
    proof_root = tmp_path / "proof2"
    meta = review_proof.capture_proof(
        BASE, HEAD, ["not-json garbage"], root=proof_root,
        run_git=lambda a: (0, "3\t1\tf.py\n", ""))
    assert meta["degraded"] is False, "capture_proof cannot see the garbled angle content"
    derived_digest = review_proof.format_proof_digest(meta, [("angle-1", 0)])
    comments = _comment(derived_digest)
    # The digest genuinely passes the merge-gate predicate:
    assert convergence_proof.non_degraded_proof_on_head(
        PR, HEAD, comments_fn=lambda _u: comments, self_login_fn=lambda: AUTHOR) is True

    findings = review_merge.merge_codereview_angles(["not-json garbage"])  # real UNPARSEABLE
    assert review_merge.is_degraded_review(findings) is True
    local_ok = review_proof.proof_present_and_nonempty(HEAD, root=proof_root)
    proof_ok, reason = _resolve(local_ok, findings=findings, comments=comments)
    assert proof_ok is False and reason == "unparseable-review-angle"
    result = _run(expects_copilot=True, reviewed=True, findings=findings, proof_ok=proof_ok)
    assert result["terminal"] == "blocked-no-independent-review"


def test_117_copilot_arm_bypass_closed(tmp_path):
    """Case 3 — #117 shape: expects_copilot=true, reviewed=True (Copilot 'reviewed'), a
    degraded angle + degraded posted digest → still blocked. Narration cannot override the
    fail-closed signal."""
    local_ok = _stage_local_artifact(tmp_path)
    findings = review_merge.merge_codereview_angles([])
    degraded_digest = review_proof.format_proof_digest({"degraded": True, "reason": "no-review-angles"})
    proof_ok, _r = _resolve(local_ok, findings=findings, comments=_comment(degraded_digest))
    result = _run(expects_copilot=True, reviewed=True, findings=findings, proof_ok=proof_ok)
    assert result["terminal"] == "blocked-no-independent-review"


def test_absent_digest_clean_angle_blocks(tmp_path):
    """Case 4 — clean findings but NO proof comment on head (the #104 shape) → blocked."""
    local_ok = _stage_local_artifact(tmp_path)
    findings = review_merge.merge_codereview_angles(["```json\n[]\n```"])  # real clean → []
    assert findings == []
    proof_ok, reason = _resolve(local_ok, findings=findings, comments=[])  # absent digest
    assert proof_ok is False and reason == "degraded-or-absent-proof-on-head"
    result = _run(expects_copilot=True, reviewed=True, findings=findings, proof_ok=proof_ok)
    assert result["terminal"] == "blocked-no-independent-review"


# ================= positive control: MUST converge =================


def test_real_clean_angle_with_nondegraded_digest_converges(tmp_path):
    """A REAL clean angle (merge_codereview_angles(['[]']) → []) + a non-degraded trusted
    digest on head + a present local artifact → proof_ok True → two-stable terminal. This
    distinguishes a real angle carrying [] findings (converges) from
    merge_codereview_angles([]) (no-angles → blocks) — the exact confusion design.md flags."""
    local_ok = _stage_local_artifact(tmp_path)
    findings = review_merge.merge_codereview_angles(["```json\n[]\n```"])
    assert findings == [] and review_merge.is_degraded_review(findings) is False
    meta = {"base": BASE, "head": HEAD, "files_changed": 3, "insertions": 5,
            "deletions": 1, "degraded": False, "reason": None}
    digest = review_proof.format_proof_digest(meta, [("correctness", 0)])
    proof_ok, reason = _resolve(local_ok, findings=findings, comments=_comment(digest))
    assert proof_ok is True and reason is None
    result = _run(expects_copilot=False, reviewed=None, findings=findings, proof_ok=proof_ok)
    assert result["terminal"] in ("two-stable", "two-stable [code-review-only]")
    assert result["state"].get("termination_reason") == "two-stable"
