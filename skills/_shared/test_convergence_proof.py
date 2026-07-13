"""test_convergence_proof.py — the autonomous-convergence review-proof-on-head predicate.

Hermetic: inject `comments_fn` / `self_login_fn` and (for the carry-ON parity fixture)
`repo_root` / `derive_base_ref_fn`; digest fixtures built via the REAL
`review_proof.format_proof_digest`; never call live gh/git.

- Group A — carry OFF (config lacks approval_survives_safe_base_sync): pure
  proof_comment_on_head. present/degraded/absent/untrusted/wrong-head/raising.
- Group B — carry ON, THIS repo's real config shape: a real tmp git repo with a
  certified base-sync chain, digest on an ancestor anchor, seams injected — proving
  non_degraded_proof_on_head is the merge gate's predicate on the DEPLOYED path.
- Group C — parity: for every fixture the boolean equals
  pred_review_proof_on_head(...).verdict == GateVerdict.PASS (one definition, no fork).
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(HERE / "fixtures") not in sys.path:
    sys.path.insert(0, str(HERE / "fixtures"))
_PR_ITERATE = HERE.parent / "tp-pr-iterate" / "scripts"
if str(_PR_ITERATE) not in sys.path:
    sys.path.insert(0, str(_PR_ITERATE))

import convergence_proof  # noqa: E402
import proof_predicate  # noqa: E402
import review_proof  # noqa: E402
from deterministic_gate import GateVerdict  # noqa: E402


PR = "https://github.com/o/r/pull/1"
HEAD = "def56789aabbccdd"
AUTHOR = "tp-loop-bot"


def _self():
    return AUTHOR


def _c(body, author=AUTHOR):
    return {"author": author, "body": body}


def _digest_for(head):
    meta = {
        "base": "base000", "head": head, "files_changed": 3,
        "insertions": 5, "deletions": 1, "degraded": False, "reason": None,
    }
    return review_proof.format_proof_digest(meta, [("correctness", 0)])


def _degraded():
    return review_proof.format_proof_digest({"degraded": True, "reason": "empty-diff"})


def _pass(verdict_source_fn):
    return verdict_source_fn().verdict == GateVerdict.PASS


# ============================================================
# Group A — carry OFF (pure proof_comment_on_head)
# ============================================================


def test_present_nondegraded_trusted_on_head_true():
    assert convergence_proof.non_degraded_proof_on_head(
        PR, HEAD, comments_fn=lambda _u: [_c(_digest_for(HEAD))], self_login_fn=_self,
    ) is True


def test_degraded_digest_on_head_false():
    assert convergence_proof.non_degraded_proof_on_head(
        PR, HEAD, comments_fn=lambda _u: [_c(_degraded())], self_login_fn=_self,
    ) is False


def test_absent_digest_false():
    assert convergence_proof.non_degraded_proof_on_head(
        PR, HEAD, comments_fn=lambda _u: [], self_login_fn=_self,
    ) is False


def test_untrusted_author_false():
    assert convergence_proof.non_degraded_proof_on_head(
        PR, HEAD, comments_fn=lambda _u: [_c(_digest_for(HEAD), author="rando")],
        self_login_fn=_self,
    ) is False


def test_digest_for_different_head_false():
    assert convergence_proof.non_degraded_proof_on_head(
        PR, HEAD, comments_fn=lambda _u: [_c(_digest_for("0000000zz"))], self_login_fn=_self,
    ) is False


def test_comments_fn_raises_false():
    def boom(_u):
        raise RuntimeError("gh failed")
    assert convergence_proof.non_degraded_proof_on_head(
        PR, HEAD, comments_fn=boom, self_login_fn=_self,
    ) is False


# ============================================================
# Group C — parity (no fork): boolean == (pred verdict is PASS)
# ============================================================


def test_group_a_parity_with_merge_gate_predicate():
    cases = [
        lambda _u: [_c(_digest_for(HEAD))],                 # PASS
        lambda _u: [_c(_degraded())],                       # INDETERMINATE
        lambda _u: [],                                      # INDETERMINATE
        lambda _u: [_c(_digest_for(HEAD), author="rando")],  # INDETERMINATE
        lambda _u: [_c(_digest_for("0000000zz"))],          # INDETERMINATE
    ]
    for fn in cases:
        boolean = convergence_proof.non_degraded_proof_on_head(
            PR, HEAD, comments_fn=fn, self_login_fn=_self,
        )
        pred = proof_predicate.pred_review_proof_on_head(
            PR, HEAD, comments_fn=fn, self_login_fn=_self,
        )
        assert boolean == (pred.verdict == GateVerdict.PASS), fn


# ============================================================
# Group B — carry ON: parity on THIS repo's real config, hermetic tmp repo
# ============================================================

_CARRY_CONFIG = {
    "review": {
        "approval_survives_safe_base_sync": True,
        "automation_identities": [AUTHOR.lower()],
    },
}


def test_carry_on_certified_ancestor_passes_and_matches_predicate(tmp_path, monkeypatch):
    """A real tmp repo with a certified 1-link base-sync; the digest is posted for the
    ANCESTOR anchor h0 (so head h1 is NOT a trusted-digest head and the carry branch
    actually runs). The boolean must be True (carry PASS) AND equal the merge gate's
    verdict==PASS — proving the seams are forwarded and this is the deployed predicate,
    not a re-implementation."""
    import base_sync_oracle
    from base_sync_repo import build_scenario, diverge_base_only, make_certified_sync_merge

    s = build_scenario(tmp_path)
    diverge_base_only(s, extra_line="### Za: advance 1\n")
    h0 = s.head()
    h1 = make_certified_sync_merge(s)
    # Seat the oracle on the scenario's own base line (the certified-chain suite posture).
    s.git("fetch", "--quiet", "origin", s.base_ref, check=True)
    s.git("checkout", "--quiet", "-B", s.base_ref, f"origin/{s.base_ref}", check=True)
    monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", lambda: s.repo_dir)

    kwargs = dict(
        comments_fn=lambda _u: [_c(_digest_for(h0))],
        self_login_fn=_self,
        config=_CARRY_CONFIG,
        repo_root=str(s.repo_dir),
        derive_base_ref_fn=lambda _u: s.base_ref,
    )
    boolean = convergence_proof.non_degraded_proof_on_head(PR, h1, **kwargs)
    pred = proof_predicate.pred_review_proof_on_head(PR, h1, **kwargs)

    assert boolean is True, "certified 1-link carry must PASS (seams forwarded, deployed path)"
    assert boolean == (pred.verdict == GateVerdict.PASS)


def test_carry_on_uncertified_head_false_and_matches_predicate(tmp_path, monkeypatch):
    """Same real repo, but the digest anchor is NOT an ancestor of head → carry cannot
    certify → INDETERMINATE → False. Parity still holds on the carry-ON path."""
    import base_sync_oracle
    from base_sync_repo import build_scenario, diverge_base_only, make_certified_sync_merge

    s = build_scenario(tmp_path)
    diverge_base_only(s, extra_line="### Za: advance 1\n")
    h1 = make_certified_sync_merge(s)
    s.git("fetch", "--quiet", "origin", s.base_ref, check=True)
    s.git("checkout", "--quiet", "-B", s.base_ref, f"origin/{s.base_ref}", check=True)
    monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", lambda: s.repo_dir)

    kwargs = dict(
        comments_fn=lambda _u: [_c(_digest_for("deadbeefdeadbeef"))],  # unrelated anchor
        self_login_fn=_self,
        config=_CARRY_CONFIG,
        repo_root=str(s.repo_dir),
        derive_base_ref_fn=lambda _u: s.base_ref,
    )
    boolean = convergence_proof.non_degraded_proof_on_head(PR, h1, **kwargs)
    pred = proof_predicate.pred_review_proof_on_head(PR, h1, **kwargs)

    assert boolean is False
    assert boolean == (pred.verdict == GateVerdict.PASS)


# ============================================================
# resolve_convergence_proof_ok — the CLI folding helper
# ============================================================


def _clean_findings():
    return []


def _unparseable_findings():
    import review_merge
    return review_merge.merge_codereview_angles(["not-json garbage"])


def _no_angles_findings():
    import review_merge
    return review_merge.merge_codereview_angles([])


def test_resolve_non_eligible_passes_through_unchanged():
    ok, reason = convergence_proof.resolve_convergence_proof_ok(
        None, eligible=False, pr_url=PR, head_sha=HEAD,
        codereview_findings=_clean_findings(), config=None,
    )
    assert ok is None and reason is None


def test_resolve_eligible_all_conjuncts_true_converges():
    ok, reason = convergence_proof.resolve_convergence_proof_ok(
        True, eligible=True, pr_url=PR, head_sha=HEAD,
        codereview_findings=_clean_findings(), config=None,
        comments_fn=lambda _u: [_c(_digest_for(HEAD))], self_login_fn=_self,
    )
    assert ok is True and reason is None


def test_resolve_eligible_unparseable_findings_blocks():
    """Non-degraded digest present + local arm present, but a garbled angle → blocked on
    the findings conjunct (the digest alone is NOT sufficient)."""
    ok, reason = convergence_proof.resolve_convergence_proof_ok(
        True, eligible=True, pr_url=PR, head_sha=HEAD,
        codereview_findings=_unparseable_findings(), config=None,
        comments_fn=lambda _u: [_c(_digest_for(HEAD))], self_login_fn=_self,
    )
    assert ok is False and reason == "unparseable-review-angle"


def test_resolve_eligible_no_angles_blocks():
    ok, reason = convergence_proof.resolve_convergence_proof_ok(
        True, eligible=True, pr_url=PR, head_sha=HEAD,
        codereview_findings=_no_angles_findings(), config=None,
        comments_fn=lambda _u: [_c(_digest_for(HEAD))], self_login_fn=_self,
    )
    assert ok is False and reason == "unparseable-review-angle"


def test_resolve_eligible_degraded_digest_blocks():
    ok, reason = convergence_proof.resolve_convergence_proof_ok(
        True, eligible=True, pr_url=PR, head_sha=HEAD,
        codereview_findings=_clean_findings(), config=None,
        comments_fn=lambda _u: [_c(_degraded())], self_login_fn=_self,
    )
    assert ok is False and reason == "degraded-or-absent-proof-on-head"


def test_resolve_eligible_local_arm_false_blocks_without_gh_call():
    """local arm already False → no digest fetch (comments_fn would raise if called)."""
    def boom(_u):
        raise AssertionError("comments_fn must not be called when local arm is False")
    ok, reason = convergence_proof.resolve_convergence_proof_ok(
        False, eligible=True, pr_url=PR, head_sha=HEAD,
        codereview_findings=_clean_findings(), config=None,
        comments_fn=boom, self_login_fn=_self,
    )
    assert ok is False and reason == "degraded-or-absent-proof-on-head"


# ============================================================
# File-size / hygiene
# ============================================================


def test_convergence_proof_under_cap():
    src = (HERE / "convergence_proof.py").read_text(encoding="utf-8")
    lines = src.count("\n") + 1
    assert lines <= 500, f"convergence_proof.py is {lines} lines (cap=500)"
    assert len(src) <= 50000
