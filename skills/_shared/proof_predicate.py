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


def _trusted_digest_heads(pr_url, *, comments_fn=None, config=None, self_login_fn=None,
                          pr_author_fn=None, head_authors=None):
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

    `pr_author_fn` (`per_developer_author: self`) adds the PR author to the trust set; a dict
    `head_authors` is filled head -> set of the trusted lowercased digest authors on it.
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
                    if pr_author_fn is None:
                        trusted = review_proof._trusted_digest_authors(config, self_login_fn)
                    else:
                        import automation_identity  # noqa: E402 — in _shared/ beside this file
                        trusted = automation_identity.trusted_digest_authors(
                            config, self_login_fn or review_proof._default_self_login_fn,
                            pr_author_fn=pr_author_fn)
                if author.lower() in trusted:
                    heads.add(m.group(1))
                    if head_authors is not None:
                        head_authors.setdefault(m.group(1), set()).add(author.lower())
        return frozenset(heads)
    except Exception:
        return None


def _self_detail(detail, anchor, carry, *, config, self_login_fn, pr_author_fn, head_authors):
    """`detail`, or the self-attested roster text (`per_developer_author.roster_detail`)."""
    try:
        if pr_author_fn is None or not (head_authors or {}).get(anchor):
            return detail
        import per_developer_author  # noqa: E402 — in _shared/ beside this file
        import review_proof  # noqa: E402
        return per_developer_author.roster_detail(
            detail, anchor, head_authors, pr_author_fn(),
            review_proof._trusted_digest_authors(config, self_login_fn), carry)
    except Exception:
        return detail


def _evaluate(pr_url, head_oid, *, comments_fn, config, self_login_fn, run_git,
              derive_base_ref_fn, repo_root, holder, pr_author_fn=None, head_authors=None):
    """Today's body: direct proof or certified base-sync carry. `holder` collects the trusted
    heads when the config-on (or `self`) path fetched them (reused by the round-log carry)."""
    sd = dict(config=config, self_login_fn=self_login_fn, pr_author_fn=pr_author_fn,
              head_authors=head_authors)
    from deterministic_gate import PredicateResult, GateVerdict  # late, circular-safe
    name = "review_proof_on_head"
    try:
        import review_proof  # noqa: E402 — in tp-pr-iterate/scripts, now on sys.path
        import base_sync_cert  # noqa: E402 — in _shared/ beside this file

        on = base_sync_cert.carry_enabled(config)
        if not on and pr_author_fn is None:
            if review_proof.proof_comment_on_head(pr_url, head_oid, comments_fn=comments_fn,
                                                  config=config, self_login_fn=self_login_fn):
                return PredicateResult(
                    name=name, verdict=GateVerdict.PASS,
                    detail="a head-bound proof comment exists on this head",
                )
            return PredicateResult(name=name, verdict=GateVerdict.INDETERMINATE,
                                   detail=_NO_PROOF_DETAIL)

        heads = _trusted_digest_heads(pr_url, comments_fn=comments_fn, config=config,
                                      self_login_fn=self_login_fn, pr_author_fn=pr_author_fn,
                                      head_authors=head_authors)
        holder.append(heads)
        if heads is None:
            return PredicateResult(name=name, verdict=GateVerdict.INDETERMINATE,
                                   detail=_NO_PROOF_DETAIL)
        if head_oid in heads:
            return PredicateResult(
                name=name, verdict=GateVerdict.PASS,
                detail=_self_detail("a head-bound proof comment exists on this head",
                                    head_oid, False, **sd),
            )
        if not on:  # `self` with carry off: a heads miss never reaches the base-sync carry
            return PredicateResult(name=name, verdict=GateVerdict.INDETERMINATE,
                                   detail=_NO_PROOF_DETAIL)

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

        import living_doc_carry  # noqa: E402 — in _shared/ beside this file

        result = base_sync_cert.find_certified_anchor(
            root, head_oid, heads, base_ref=base_ref,
            max_links=base_sync_cert.carry_max_chain(config), run_git=run_git,
            carry_handres=living_doc_carry.carry_livingdoc_handres_enabled(config),
        )
        if result.certified:
            sha7 = (result.anchor or "")[:7]
            return PredicateResult(
                name=name, verdict=GateVerdict.PASS,
                detail=_self_detail(
                    f"proof comment carried across {result.links} certified "
                    f"base-sync merge(s) (anchor {sha7})", result.anchor, True, **sd),
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


def _round_log_carry(r, pr_url, head_oid, holder, kw):
    """After a non-PASS `r`: if head is only round-log commits above a trusted-proof anchor,
    PASS (config-on may also compose the base-sync carry from the anchor). Else `r`."""
    from deterministic_gate import PredicateResult, GateVerdict  # late, circular-safe
    try:
        import base_sync_cert  # noqa: E402
        import round_log_carry  # noqa: E402
        config = kw["config"]
        on = base_sync_cert.carry_enabled(config)
        if holder:
            heads = holder[0]
        else:
            heads = _trusted_digest_heads(
                pr_url, comments_fn=kw["comments_fn"], config=config,
                self_login_fn=kw["self_login_fn"], pr_author_fn=kw["pr_author_fn"],
                head_authors=kw["head_authors"])
        if not heads:
            return r
        root = kw["repo_root"]
        if root is None:
            import project_root  # noqa: E402
            root = project_root.find_project_root()
        if root is None:
            return r
        res = round_log_carry.strip_round_log_commits(root, head_oid, run_git=kw["run_git"])
        kind = "round-log"
        import merge_carry  # noqa: E402 — in _shared/ beside this file
        base_ref_fn = merge_carry.lazy_base_ref(pr_url, kw["derive_base_ref_fn"])  # one gh call, if any
        if not (res.links and res.anchor in heads):
            import proof_neutral_carry  # noqa: E402 — in _shared/ beside this file
            if proof_neutral_carry.proof_neutral_carry_enabled(config):
                nres = proof_neutral_carry.strip_proof_neutral_commits(
                    root, head_oid, run_git=kw["run_git"], stop_at=frozenset(heads),
                    base_ref=base_ref_fn)
                if nres.anchor and nres.links and (nres.neutral_links > 0 or nres.anchor in heads):
                    res = nres
                    kind = "proof-neutral" if nres.neutral_links else "round-log"
        if not res.links or not res.anchor:
            return r
        detail = (f"proof comment carried across {res.links} {kind} commit(s) "
                  f"(anchor {res.anchor[:7]})")
        sd = dict(config=config, self_login_fn=kw["self_login_fn"],
                  pr_author_fn=kw["pr_author_fn"], head_authors=kw["head_authors"])
        if res.anchor in heads:
            return PredicateResult(name=r.name, verdict=GateVerdict.PASS,
                                   detail=_self_detail(detail, res.anchor, True, **sd))
        if not on:
            return r
        base_ref = base_ref_fn()
        if not base_ref:
            return r
        import living_doc_carry  # noqa: E402 — in _shared/ beside this file

        cert = base_sync_cert.find_certified_anchor(
            root, res.anchor, heads, base_ref=base_ref,
            max_links=base_sync_cert.carry_max_chain(config), run_git=kw["run_git"],
            carry_handres=living_doc_carry.carry_livingdoc_handres_enabled(config))
        if cert.certified:
            both = _self_detail(
                f"proof comment carried across {cert.links} certified base-sync "
                f"merge(s) (anchor {(cert.anchor or '')[:7]})", cert.anchor, True, **sd)
            return PredicateResult(name=r.name, verdict=GateVerdict.PASS,
                                   detail=f"{detail}; {both}")
        return r
    except Exception:
        return r


def pred_review_proof_on_head(pr_url, head_oid, *, comments_fn=None, config=None,
                              self_login_fn=None, run_git=None, derive_base_ref_fn=None,
                              repo_root=None, head_fn=None):
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

    Under `github.per_developer_author: self` (an invalid value reads as `off`) the PR author
    joins the trust set (`head_fn`: one fetch per evaluation) and the heads path runs even with
    carry off; the roster detail then says self-attested. A fork PR or automation author never counts.

    A proof also carries across up to a few round-log commits (a terminal review-log
    flush that only adds to the archived design's log files; `round_log_carry`), so the
    two-stable flush push does not stale a converged review.
    It also carries across up to 4 proof-neutral commits (living-doc `.md` edits, comment-only
    `.py` edits and a base-sync merge whose hand-resolved paths are all living docs, within 200
    changed lines; `proof_neutral_carry`, default ON, `review.proof_neutral_carry: false`
    disables); the ci-local stamp is never carried over them.

    NEVER FAIL (D6, mirrors pred_human_approved / pred_copilot_on_head): a later
    proof-bearing review (or a later certified base-sync) + re-evaluation flips
    INDETERMINATE → PASS, no other change. Wraps all in try/except → INDETERMINATE on
    any internal error. NEVER raises.
    """
    from deterministic_gate import PredicateResult, GateVerdict  # late, circular-safe
    name = "review_proof_on_head"
    try:
        holder = []
        pr_author_fn = head_authors = None
        import automation_identity  # noqa: E402 — in _shared/ beside this file
        if automation_identity._gate_mode(config) == "self":
            import per_developer_author  # noqa: E402
            pr_author_fn = per_developer_author.pr_author_fn_for(pr_url, head_fn)
            head_authors = {}
        kw = dict(comments_fn=comments_fn, config=config, self_login_fn=self_login_fn,
                  run_git=run_git, derive_base_ref_fn=derive_base_ref_fn,
                  repo_root=repo_root, holder=holder, pr_author_fn=pr_author_fn,
                  head_authors=head_authors)
        r = _evaluate(pr_url, head_oid, **kw)
        if r.verdict == GateVerdict.PASS:
            return r
        return _round_log_carry(r, pr_url, head_oid, holder, kw)
    except Exception:
        return PredicateResult(
            name=name, verdict=GateVerdict.INDETERMINATE,
            detail="internal error evaluating review proof",
        )
