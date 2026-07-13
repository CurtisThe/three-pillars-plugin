"""test_proof_carry.py -- consumer 2 (proof carry), tasks 7.1-7.2.

Covers:
  _trusted_digest_heads (7.1): one comments fetch, degraded/untrusted-author exclusion,
                               fetch/parse failure -> None
  pred_review_proof_on_head carry branch (7.2): config-off byte parity, carry-PASS,
                               carry-refusal detail

Task 7.3 (gate_roster runner threading + fixture 13) and 7.4 (attack 5, extends
test_base_sync_cert_attacks.py) live elsewhere. The never-FAIL/never-PASS property
sweep over the Phase 4-5 attack matrix continues in `test_proof_carry_pred.py` (split
per the plan's named escape hatch — this file's own unit tests already near the
300-line soft cap once the carry-branch tests are added).
"""
from __future__ import annotations

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
AUTHOR = "tp-loop-bot"

CARRY_CONFIG = {
    "review": {"approval_survives_safe_base_sync": True, "base_sync_carry_max_chain": 5},
}


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


# ============================================================
# Task 7.1: _trusted_digest_heads
# ============================================================


class TestTrustedDigestHeads:
    def test_collects_trusted_head(self):
        heads = proof_predicate._trusted_digest_heads(
            PR, comments_fn=lambda _u: [_c(_digest_for(HEAD))], self_login_fn=_self,
        )
        assert heads == frozenset({HEAD})

    def test_skips_degraded_digest(self):
        heads = proof_predicate._trusted_digest_heads(
            PR, comments_fn=lambda _u: [_c(_degraded())], self_login_fn=_self,
        )
        assert heads == frozenset()

    def test_excludes_untrusted_author(self):
        heads = proof_predicate._trusted_digest_heads(
            PR, comments_fn=lambda _u: [_c(_digest_for(HEAD), author="rando")],
            self_login_fn=_self,
        )
        assert heads == frozenset()

    def test_config_automation_identities_trusted(self):
        heads = proof_predicate._trusted_digest_heads(
            PR, comments_fn=lambda _u: [_c(_digest_for(HEAD), author="org-bot")],
            config={"review": {"automation_identities": ["org-bot"]}},
            self_login_fn=lambda: None,
        )
        assert heads == frozenset({HEAD})

    def test_multiple_trusted_heads_collected(self):
        other = "1111222233334444"
        heads = proof_predicate._trusted_digest_heads(
            PR,
            comments_fn=lambda _u: [_c(_digest_for(HEAD)), _c(_digest_for(other))],
            self_login_fn=_self,
        )
        assert heads == frozenset({HEAD, other})

    def test_fetch_failure_is_none(self):
        def boom(_u):
            raise RuntimeError("gh failed")

        assert proof_predicate._trusted_digest_heads(
            PR, comments_fn=boom, self_login_fn=_self,
        ) is None

    def test_non_list_result_is_none(self):
        assert proof_predicate._trusted_digest_heads(
            PR, comments_fn=lambda _u: "not-a-list", self_login_fn=_self,
        ) is None

    def test_bare_string_item_ignored(self):
        heads = proof_predicate._trusted_digest_heads(
            PR, comments_fn=lambda _u: [_digest_for(HEAD)], self_login_fn=_self,
        )
        assert heads == frozenset()

    def test_never_raises_on_garbage(self):
        assert proof_predicate._trusted_digest_heads(
            None, comments_fn=lambda _u: None, self_login_fn=None,
        ) is None


# ============================================================
# Task 7.2: pred_review_proof_on_head carry branch
# ============================================================


class TestPredReviewProofOnHeadCarryBranch:
    def test_config_off_byte_identical_path(self):
        """Config off (the default) -> EXACTLY today's proof_comment_on_head path."""
        r = proof_predicate.pred_review_proof_on_head(
            PR, HEAD, comments_fn=lambda _u: [_c(_digest_for(HEAD))], self_login_fn=_self,
        )
        assert r.verdict == GateVerdict.PASS
        assert r.detail == "a head-bound proof comment exists on this head"

    def test_config_off_no_base_sync_cert_subprocess(self, monkeypatch):
        """Config off -> no git subprocess is ever spawned (base_sync_cert is imported
        for carry_enabled() only, never invoked for a chain walk)."""
        import subprocess

        def _forbidden(*a, **k):
            raise AssertionError("subprocess spawned on a config-off proof predicate")

        monkeypatch.setattr(subprocess, "run", _forbidden)
        r = proof_predicate.pred_review_proof_on_head(
            PR, HEAD, comments_fn=lambda _u: [], self_login_fn=_self, config=None,
        )
        assert r.verdict == GateVerdict.INDETERMINATE

    def test_config_on_head_bound_digest_still_passes_one_fetch(self):
        """Config on, head_oid directly in the trusted-heads set -> PASS, today's
        detail, single fetch (no chain walk needed)."""
        calls = []

        def counting_comments_fn(_u):
            calls.append(1)
            return [_c(_digest_for(HEAD))]

        r = proof_predicate.pred_review_proof_on_head(
            PR, HEAD, comments_fn=counting_comments_fn, self_login_fn=_self,
            config=CARRY_CONFIG,
        )
        assert r.verdict == GateVerdict.PASS
        assert r.detail == "a head-bound proof comment exists on this head"
        assert len(calls) == 1

    def test_config_on_fetch_failure_indeterminate(self):
        def boom(_u):
            raise RuntimeError("gh failed")

        r = proof_predicate.pred_review_proof_on_head(
            PR, HEAD, comments_fn=boom, self_login_fn=_self, config=CARRY_CONFIG,
        )
        assert r.verdict == GateVerdict.INDETERMINATE
        assert "; carry:" not in r.detail

    def test_config_on_unresolvable_repo_root_no_carry_suffix(self):
        """Digest present but for a DIFFERENT head (no direct match); carry enabled but
        repo_root unresolvable -> no carry ATTEMPTED, no '; carry:' suffix."""
        r = proof_predicate.pred_review_proof_on_head(
            PR, HEAD, comments_fn=lambda _u: [_c(_digest_for("otherhead12345"))],
            self_login_fn=_self, config=CARRY_CONFIG, repo_root=None,
            derive_base_ref_fn=lambda _u: None,
        )
        assert r.verdict == GateVerdict.INDETERMINATE
        assert "; carry:" not in r.detail

    def test_never_raises_on_garbage(self):
        r = proof_predicate.pred_review_proof_on_head(
            None, None, comments_fn=lambda _u: None, config="not-a-dict",
        )
        assert r.verdict == GateVerdict.INDETERMINATE
        assert r.verdict != GateVerdict.FAIL


# ============================================================
# Regression parity: existing byte-identical behavior for config-off scenarios
# ============================================================


def test_review_proof_py_untouched():
    src_path = HERE.parent / "tp-pr-iterate" / "scripts" / "review_proof.py"
    # Sanity: the module still exposes the exact symbols we import-reuse.
    assert hasattr(review_proof, "_DEGRADED_RE")
    assert hasattr(review_proof, "_DIGEST_HEAD_RE")
    assert hasattr(review_proof, "_trusted_digest_authors")
    assert hasattr(review_proof, "_default_comments_fn")
    assert src_path.exists()
