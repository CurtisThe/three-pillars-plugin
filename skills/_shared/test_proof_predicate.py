"""test_proof_predicate.py — the merge-gate review-proof-on-head predicate (B5).

Hermetic: inject comments_fn + self_login_fn; never calls live gh/git. Digest
fixtures built via the REAL format_proof_digest. Asserts PASS on a head-bound
TRUSTED-authored posted comment and INDETERMINATE on absent/degraded/
untrusted-author/raising arms — NEVER FAIL (D6).
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
_PR_ITERATE = HERE.parent / "tp-pr-iterate" / "scripts"
if str(_PR_ITERATE) not in sys.path:
    sys.path.insert(0, str(_PR_ITERATE))

import review_proof  # noqa: E402
import proof_predicate  # noqa: E402
from deterministic_gate import GateVerdict  # noqa: E402


PR = "https://github.com/o/r/pull/1"
HEAD = "def56789aabbccdd"

# The fixtures' own self login — the only hardcoded-trusted identity after the
# round-2 narrowing (the Copilot/native-bot floor is NOT digest-trusted; see
# test_review_proof_detectors.py for the author-dimension unit tests).
AUTHOR = "tp-loop-bot"


def _self():
    return AUTHOR


def _no_self():
    return None


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


def test_pred_proof_posted_head_bound_pass():
    r = proof_predicate.pred_review_proof_on_head(
        PR, HEAD, comments_fn=lambda _u: [_c(_digest_for(HEAD))],
        self_login_fn=_self,
    )
    assert r.verdict == GateVerdict.PASS


def test_pred_proof_missing_indeterminate():
    r = proof_predicate.pred_review_proof_on_head(
        PR, HEAD, comments_fn=lambda _u: [], self_login_fn=_self,
    )
    assert r.verdict == GateVerdict.INDETERMINATE


def test_pred_proof_degraded_indeterminate():
    r = proof_predicate.pred_review_proof_on_head(
        PR, HEAD, comments_fn=lambda _u: [_c(_degraded())], self_login_fn=_self,
    )
    assert r.verdict == GateVerdict.INDETERMINATE


def test_pred_proof_prior_head_indeterminate():
    r = proof_predicate.pred_review_proof_on_head(
        PR, HEAD, comments_fn=lambda _u: [_c(_digest_for("0000000zz"))],
        self_login_fn=_self,
    )
    assert r.verdict == GateVerdict.INDETERMINATE


def test_pred_proof_untrusted_author_indeterminate():
    """A perfect head-bound digest from a NON-automation author is not proof
    (review finding on PR #109 — any commenter could fabricate the digest)."""
    r = proof_predicate.pred_review_proof_on_head(
        PR, HEAD, comments_fn=lambda _u: [_c(_digest_for(HEAD), author="rando")],
        self_login_fn=_self,
    )
    assert r.verdict == GateVerdict.INDETERMINATE
    assert r.verdict != GateVerdict.FAIL


def test_pred_proof_self_login_fn_threaded():
    """self_login_fn reaches the trusted-author set (the framework's own login)."""
    r = proof_predicate.pred_review_proof_on_head(
        PR, HEAD, comments_fn=lambda _u: [_c(_digest_for(HEAD), author="tp-bot")],
        self_login_fn=lambda: "tp-bot",
    )
    assert r.verdict == GateVerdict.PASS


def test_pred_proof_config_extras_threaded():
    """config review.automation_identities reaches the trusted-author set."""
    r = proof_predicate.pred_review_proof_on_head(
        PR, HEAD, comments_fn=lambda _u: [_c(_digest_for(HEAD), author="org-bot")],
        config={"review": {"automation_identities": ["org-bot"]}},
        self_login_fn=_no_self,
    )
    assert r.verdict == GateVerdict.PASS


def test_pred_proof_comments_fn_raises_indeterminate():
    def boom(_u):
        raise RuntimeError("gh failed")
    r = proof_predicate.pred_review_proof_on_head(
        PR, HEAD, comments_fn=boom, self_login_fn=_self,
    )
    assert r.verdict == GateVerdict.INDETERMINATE
    assert r.verdict != GateVerdict.FAIL


def test_pred_proof_never_fail():
    cases = [
        lambda _u: [_c(_digest_for(HEAD))],                    # PASS
        lambda _u: [],                                         # INDETERMINATE
        lambda _u: [_c(_degraded())],                          # INDETERMINATE
        lambda _u: [_c(_digest_for(HEAD), author="rando")],    # INDETERMINATE
        lambda _u: [_digest_for(HEAD)],                        # bare str → INDET
        lambda _u: "not-a-list",                               # INDETERMINATE
    ]
    for fn in cases:
        r = proof_predicate.pred_review_proof_on_head(
            PR, HEAD, comments_fn=fn, self_login_fn=_self,
        )
        assert r.verdict in (GateVerdict.PASS, GateVerdict.INDETERMINATE)
        assert r.verdict != GateVerdict.FAIL


def test_pred_proof_name_string():
    r = proof_predicate.pred_review_proof_on_head(
        PR, HEAD, comments_fn=lambda _u: [], self_login_fn=_self,
    )
    assert r.name == "review_proof_on_head"


def test_pred_proof_config_accepted():
    # config threads through alongside the require toggle (applied by the roster).
    r = proof_predicate.pred_review_proof_on_head(
        PR, HEAD, comments_fn=lambda _u: [_c(_digest_for(HEAD))],
        config={"review": {"require_review_proof": True}},
        self_login_fn=_self,
    )
    assert r.verdict == GateVerdict.PASS


def test_proof_predicate_under_cap():
    src = (HERE / "proof_predicate.py").read_text(encoding="utf-8")
    lines = src.count("\n") + 1
    assert lines <= 500, f"proof_predicate.py is {lines} lines (cap=500)"
    assert len(src) <= 50000


def test_proof_predicate_c1_clean():
    src = (HERE / "proof_predicate.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = (alias.name or "").lower()
                assert "anthropic" not in name and "claude_agent" not in name
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").lower()
            assert "anthropic" not in module and "claude_agent" not in module
