"""convergence_proof.py — the autonomous-convergence review-proof-on-head predicate.

DRY with the merge gate (design.md Constraint "DRY with the merge gate"): this module
holds NO second implementation of the digest format or the on-head predicate. It
DELEGATES to `proof_predicate.pred_review_proof_on_head` — the exact predicate the
`/tp-merge` gate reads (which itself reuses `review_proof._DIGEST_HEAD_RE` /
`_DEGRADED_RE` / `proof_comment_on_head` / `_trusted_digest_heads` by import;
`review_proof.py` is at the 500-line cap and gets ZERO additions). Binding the
autonomous-convergence declaration to this predicate makes convergence STRICTER than
the merge gate: convergence ⟹ the gate would PASS the same head.

Fail-closed: any INDETERMINATE verdict (degraded digest / absent digest / fetch-or-
parse failure / uncertified base-sync carry) → False. Stdlib-only; total; never raises.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PR_ITERATE = _HERE.parent / "tp-pr-iterate" / "scripts"
for _p in (_HERE, _PR_ITERATE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def non_degraded_proof_on_head(pr_url, head_oid, *, comments_fn=None, config=None,
                               self_login_fn=None, run_git=None, derive_base_ref_fn=None,
                               repo_root=None) -> bool:
    """True iff a non-degraded, trusted-authored proof digest is on the current head
    (directly OR via a certified base-sync carry) — the SAME question the merge gate
    answers, via the SAME predicate.

    Delegates to `proof_predicate.pred_review_proof_on_head` and returns
    `result.verdict == GateVerdict.PASS`. INDETERMINATE → False (fail-closed).

    The `run_git` / `derive_base_ref_fn` / `repo_root` pass-throughs are load-bearing on
    THIS repo: `.three-pillars/config.json` sets
    `review.approval_survives_safe_base_sync=true`, so `pred_review_proof_on_head`
    engages its base-sync-carry branch (live `gh pr view` + git subprocess via
    `project_root.find_project_root()` / `diff_balloon_guard.derive_base_ref`) whenever
    the exact head is not already a trusted-digest head — exactly the degraded/absent
    scenarios under test. Forwarding the seams keeps hermetic callers off live gh/git and
    lets them drive the DEPLOYED carry-ON shape. Total; never raises.
    """
    try:
        from proof_predicate import pred_review_proof_on_head
        from deterministic_gate import GateVerdict
        result = pred_review_proof_on_head(
            pr_url, head_oid, comments_fn=comments_fn, config=config,
            self_login_fn=self_login_fn, run_git=run_git,
            derive_base_ref_fn=derive_base_ref_fn, repo_root=repo_root,
        )
        return result.verdict == GateVerdict.PASS
    except Exception:
        return False


def resolve_convergence_proof_ok(local_proof_ok, *, eligible, pr_url, head_sha,
                                 codereview_findings, config,
                                 comments_fn=None, self_login_fn=None):
    """Fold the CLI's convergence `proof_ok` on a convergence-eligible round.

    On an eligible round convergence requires ALL of, as fail-closed ANDs:
      - the local-artifact / ground arm (`local_proof_ok`, already computed by the CLI),
      - a non-degraded trusted proof digest on head (`non_degraded_proof_on_head` — the
        #104/#117 posted-digest shape), AND
      - non-degraded merged review findings (`not is_degraded_review(codereview_findings)`).

    The findings conjunct is INDEPENDENT and load-bearing: `review_proof.capture_proof`
    computes `degraded` from numstat-emptiness + angle_count ONLY — it can NOT see a
    garbled non-JSON angle whose posted digest is (wrongly) non-degraded. The merged
    findings DO reflect that parse failure, and `merge_codereview_angles([])` (NO-ANGLES)
    is caught by the same conjunct.

    Returns `(proof_ok, not_converged_reason)`. On a NON-eligible round returns
    `(local_proof_ok, None)` unchanged — no digest fetch, no block, `proof_ok=None`
    preserved for the CLI's non-convergence rounds. Never raises (both conjunct helpers
    are themselves fail-closed).
    """
    if not eligible:
        return local_proof_ok, None
    import review_merge  # in tp-pr-iterate/scripts, on sys.path (module import above)
    proof_ok = bool(local_proof_ok)
    reason = None
    # Unparseable/no-angles conjunct FIRST: capture_proof (numstat + angle_count) can't
    # see a garbled parse; the merged findings can.
    if proof_ok and review_merge.is_degraded_review(codereview_findings):
        proof_ok = False
        reason = "unparseable-review-angle"
    # Posted-digest conjunct: the SAME predicate the merge gate reads (fetch only when the
    # cheaper conjuncts still admit convergence — no spurious live gh once already blocked).
    if proof_ok and not non_degraded_proof_on_head(
            pr_url, head_sha, config=config,
            comments_fn=comments_fn, self_login_fn=self_login_fn):
        proof_ok = False
        reason = "degraded-or-absent-proof-on-head"
    if not proof_ok and reason is None:
        # local arm already False (no-root eligible round, or degraded/absent artifact).
        reason = "degraded-or-absent-proof-on-head"
    return proof_ok, reason
