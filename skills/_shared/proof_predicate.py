"""proof_predicate.py — the merge-gate review-proof-on-head predicate.

Split out of deterministic_gate.py (850 lines, over cap) and gate_roster.py
(wiring, not predicate defs) per detailed-design OQ2. Stdlib-only, C1-clean.
Imports PredicateResult/GateVerdict via late import (gate_roster's circular-dep
pattern). The predicate NEVER returns FAIL (D6) — PASS or INDETERMINATE only.

Task 7.1/7.2 (approval-survives-safe-base-sync consumer 2): `_trusted_digest_heads`
+ the carry branch REUSE `review_proof`'s digest-format primitives by import
(`_DEGRADED_RE`, `_DIGEST_HEAD_RE`, `_trusted_digest_authors`,
`_default_comments_fn`) — `review_proof.py` (at the 500-line hard cap) gets ZERO
additions; there is no second implementation of the digest format anywhere here.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PR_ITERATE = _HERE.parent / "tp-pr-iterate" / "scripts"
if str(_PR_ITERATE) not in sys.path:
    sys.path.insert(0, str(_PR_ITERATE))

_NO_PROOF_DETAIL = (
    "no head-bound proof comment from a trusted automation author "
    "— run the proof-bearing review on the current head"
)


def _trusted_digest_heads(pr_url, *, comments_fn=None, config=None, self_login_fn=None):
    """ONE comments fetch → the `frozenset` of full-SHA heads carried by a
    TRUSTED-authored, non-degraded proof digest — or `None` on a fetch/parse
    failure (fail-closed; distinct from a proven-empty, successful fetch, which
    returns an empty frozenset).

    Per trusted-authored comment, per line: `review_proof._DEGRADED_RE` hits are
    skipped (a degraded digest is never proof); `review_proof._DIGEST_HEAD_RE`
    matches are collected. Author trust (`review_proof._trusted_digest_authors`) is
    built LAZILY — only once a digest-shaped line is actually seen — mirroring
    `review_proof.proof_comment_on_head`'s own lazy-trust discipline (a garbage
    comment must never trigger a live `gh api user` call). Total, never raises.
    """
    try:
        import review_proof  # noqa: E402 — in tp-pr-iterate/scripts, now on sys.path

        fn = comments_fn or review_proof._default_comments_fn
        items = fn(pr_url)
        if not isinstance(items, list):
            return None
        heads = set()
        trusted = None
        for item in items:
            if not isinstance(item, dict):
                continue
            author = item.get("author")
            if not isinstance(author, str) or not author:
                continue
            body = item.get("body")
            text = body if isinstance(body, str) else str(body or "")
            for line in text.splitlines():
                if review_proof._DEGRADED_RE.search(line):
                    continue
                m = review_proof._DIGEST_HEAD_RE.search(line)
                if not m:
                    continue
                if trusted is None:
                    trusted = review_proof._trusted_digest_authors(config, self_login_fn)
                if author.lower() in trusted:
                    heads.add(m.group(1))
        return frozenset(heads)
    except Exception:
        return None


def pred_review_proof_on_head(pr_url, head_oid, *, comments_fn=None, config=None,
                              self_login_fn=None, run_git=None, derive_base_ref_fn=None,
                              repo_root=None):
    """Gate predicate: was THIS head reviewed-with-proof (posted digest comment),
    directly OR via a certified no-op base-sync carry from a proof-bearing ancestor?

    Config OFF (the default) is EXACTLY today's `proof_comment_on_head` path — byte-
    identical behavior, one fetch, no git subprocess and no chain walk (`base_sync_cert`
    is imported only for the cheap `carry_enabled` config check).

    Config ON: a SINGLE comments fetch via `_trusted_digest_heads`. `None` (fetch/parse
    failure) → INDETERMINATE with today's remediation detail. `head_oid` present in the
    trusted-heads set → PASS with today's detail (equivalent semantics, one fetch).
    Otherwise `base_sync_cert.find_certified_anchor(repo_root, head_oid, heads,
    base_ref=..., max_links=...)`: certified → PASS "proof comment carried across N
    certified base-sync merge(s) (anchor <sha7>)"; not certified → INDETERMINATE with
    "; carry: <reason>" appended to today's remediation detail. `repo_root` defaults to
    `project_root.find_project_root()`; `base_ref` via `derive_base_ref_fn(pr_url)` or
    `diff_balloon_guard.derive_base_ref(pr_url)`. An unresolvable repo_root/base_ref
    means "no carry attempted" — no "; carry:" suffix.

    NEVER FAIL (D6, mirrors pred_human_approved / pred_copilot_on_head): a later
    proof-bearing review (or a later certified base-sync) + re-evaluation flips
    INDETERMINATE → PASS, no other change. Wraps all in try/except → INDETERMINATE on
    any internal error. NEVER raises.
    """
    from deterministic_gate import PredicateResult, GateVerdict  # late, circular-safe
    name = "review_proof_on_head"
    try:
        import review_proof  # noqa: E402 — in tp-pr-iterate/scripts, now on sys.path
        import base_sync_cert  # noqa: E402 — in _shared/ beside this file

        if not base_sync_cert.carry_enabled(config):
            if review_proof.proof_comment_on_head(pr_url, head_oid, comments_fn=comments_fn,
                                                  config=config, self_login_fn=self_login_fn):
                return PredicateResult(
                    name=name, verdict=GateVerdict.PASS,
                    detail="a head-bound proof comment exists on this head",
                )
            return PredicateResult(name=name, verdict=GateVerdict.INDETERMINATE,
                                   detail=_NO_PROOF_DETAIL)

        heads = _trusted_digest_heads(pr_url, comments_fn=comments_fn, config=config,
                                      self_login_fn=self_login_fn)
        if heads is None:
            return PredicateResult(name=name, verdict=GateVerdict.INDETERMINATE,
                                   detail=_NO_PROOF_DETAIL)
        if head_oid in heads:
            return PredicateResult(
                name=name, verdict=GateVerdict.PASS,
                detail="a head-bound proof comment exists on this head",
            )

        root = repo_root
        if root is None:
            import project_root  # noqa: E402 — in _shared/ beside this file
            root = project_root.find_project_root()
        if root is None:
            return PredicateResult(name=name, verdict=GateVerdict.INDETERMINATE,
                                   detail=_NO_PROOF_DETAIL)

        if derive_base_ref_fn is not None:
            base_ref = derive_base_ref_fn(pr_url)
        else:
            import diff_balloon_guard  # noqa: E402 — in _shared/ beside this file
            base_ref = diff_balloon_guard.derive_base_ref(pr_url)
        if not base_ref:
            return PredicateResult(name=name, verdict=GateVerdict.INDETERMINATE,
                                   detail=_NO_PROOF_DETAIL)

        result = base_sync_cert.find_certified_anchor(
            root, head_oid, heads, base_ref=base_ref,
            max_links=base_sync_cert.carry_max_chain(config), run_git=run_git,
        )
        if result.certified:
            sha7 = (result.anchor or "")[:7]
            return PredicateResult(
                name=name, verdict=GateVerdict.PASS,
                detail=(
                    f"proof comment carried across {result.links} certified "
                    f"base-sync merge(s) (anchor {sha7})"
                ),
            )
        return PredicateResult(
            name=name, verdict=GateVerdict.INDETERMINATE,
            detail=f"{_NO_PROOF_DETAIL}; carry: {result.reason}",
        )
    except Exception:
        return PredicateResult(
            name=name, verdict=GateVerdict.INDETERMINATE,
            detail="internal error evaluating review proof",
        )
