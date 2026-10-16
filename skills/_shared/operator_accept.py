#!/usr/bin/env python3
"""operator_accept.py — the operator-accept token and its merge-gate predicate (E3).

An operator who cannot leave a native APPROVED review (a `gh`-less seat, a
headless run) can still authorise a merge in prose: a review body line

    tp-accept: <full-40-hex head sha> <reason>

`pred_operator_accept` reads that line off the PR's REST review payloads and PASSes
only when the LATEST review of a HUMAN author is APPROVED, current on the head, and
accepts that exact sha. Behavior 16: the accept is bound to one head — a different
head, a bot/automation author, a COMMENTED or CHANGES_REQUESTED review, an
unresolvable self login or a failed fetch is INDETERMINATE. NEVER FAIL, never raises
(a missing observation is unprovable, not a violation).

stdlib-only. Sibling modules import by bare name; `deterministic_gate` /
`human_approval` are imported lazily inside the functions (both sides of that pair
import each other late).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ---- sys.path: ensure _shared/ is on path so sibling modules are importable ----
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

# Full 40-hex sha ONLY: a 7-char prefix would let an accept written for one head be
# read onto another. The reason is mandatory — an accept with no reason is prose.
ACCEPT_RE = re.compile(r"^tp-accept:\s+([0-9a-fA-F]{40})\s+(\S.*)$", re.M)

NO_ACCEPT_DETAIL = "no operator-accept on head"
GITEA_LINE = "operator-accept unavailable on gitea (gitea-forge-adapter)"


def parse_accept(body) -> "tuple[str, str] | None":
    """The `(sha, reason)` of a `tp-accept:` line in `body`, or None.

    Total: a non-str body, a prefix sha, a 39/41-char sha, a non-hex sha, a missing
    sha or a missing reason all fold to None. The reason keeps its inner words and
    spaces (it is printed verbatim in the gate detail and the `/tp-merge` line).
    """
    if not isinstance(body, str):
        return None
    match = ACCEPT_RE.search(body)
    if match is None:
        return None
    return match.group(1), match.group(2).strip()


def _latest_human_reviews(reviews, automation) -> list:
    """Each human author's LATEST review (grouped by lowercased login).

    The author dimension is load-bearing: an author whose latest review is COMMENTED
    or CHANGES_REQUESTED is excluded even when an EARLIER review of theirs was an
    APPROVED accept — the later review is what that author currently stands behind.
    Bot/automation authors are filtered out BEFORE the grouping, so a trailing bot
    review can never clobber a human's standing accept.
    """
    import human_approval_review  # noqa: E402 — adapts review["user"] to the actor floor

    if not isinstance(reviews, list):
        return []
    latest: dict = {}
    for review in reviews:
        if not human_approval_review._review_author_is_human(review, automation):
            continue
        login = (review.get("user") or {}).get("login", "").lower()
        current = latest.get(login)
        if current is None or str(review.get("submitted_at") or "") > str(
                current.get("submitted_at") or ""):
            latest[login] = review
    return list(latest.values())


def _build_live_runners(pr_url) -> dict:
    """This predicate's live `*_fn`s, delegated to `human_approval` (same `gh` calls,
    same fail-closed raises). One seam per module: a hermetic CLI test patches this
    name and never reaches into a sibling's private helper.
    """
    import human_approval  # noqa: E402 — in _shared/ beside this file

    return human_approval._build_live_runners(pr_url)


def _accept_detail(reviews, head_oid, automation) -> "str | None":
    """The PASS detail when one author's latest review is an accept of THIS head.

    Three conjuncts on that latest review: `state == "APPROVED"`, `commit_id` is the
    head (the review itself is current, not merely its body), and its body parses to
    `sha == head_oid`. Detail: `operator-accept by <login> on <sha7>: <reason>`.
    """
    for review in _latest_human_reviews(reviews, automation):
        if review.get("state") != "APPROVED":
            continue
        if str(review.get("commit_id") or "").lower() != str(head_oid or "").lower():
            continue
        parsed = parse_accept(review.get("body"))
        if parsed is None or parsed[0].lower() != str(head_oid or "").lower():
            continue
        login = (review.get("user") or {}).get("login") or "?"
        return f"operator-accept by {login} on {str(head_oid)[:7]}: {parsed[1]}"
    return None


def pred_operator_accept(pr_url, head_oid, *, runners=None,
                         config=None) -> "object":
    """Gate predicate: is there an OPERATOR-ACCEPT for `head_oid` on this PR?

    PASS  → `operator-accept by <login> on <sha7>: <reason>`
    INDETERMINATE → "no operator-accept on head" (absent / another head / a bot or
                    the self login / a COMMENTED or CHANGES_REQUESTED latest review
                    / any unprovable case)
    NEVER FAIL, never raises.

    Runner keys resolve PER-KEY against the live `gh` runners (mirrors
    `human_approval.approved_on_head_result`): an injected dict never triggers a live
    runner build. Only `self_login_fn` and `reviews_fn` are used — the REST review
    payload already carries `body`, so no extra fetch. The self login joins the
    automation set, so the bot's own accept never counts; an unresolvable self login
    fails CLOSED (the automation set must not be silently shrunk).
    """
    from deterministic_gate import GateVerdict, PredicateResult  # lazy: late-cycle pair

    detail = None
    try:
        import human_approval  # noqa: E402 — identity floor + live runners + _safe_fetch

        provided = runners or {}
        live = None

        def _resolve(key):
            nonlocal live
            fn = provided.get(key)
            if fn is not None:
                return fn
            if live is None:
                live = _build_live_runners(pr_url)
            return live[key]

        try:
            self_login = _resolve("self_login_fn")()
        except Exception:
            self_login = None
        if isinstance(self_login, str) and self_login:
            automation = human_approval.automation_identities(
                self_login=self_login, config=config)
            reviews = human_approval._safe_fetch(_resolve("reviews_fn"), pr_url,
                                                 default=[])
            detail = _accept_detail(reviews, head_oid, automation)
    except Exception:
        detail = None

    if detail:
        return PredicateResult("operator_accept", GateVerdict.PASS, detail)
    return PredicateResult("operator_accept", GateVerdict.INDETERMINATE,
                           NO_ACCEPT_DETAIL)


def accept_for(pr_url, head_oid, r, config, running_live):
    """The roster's accept thunk for the proof slot, per the `r[...]` seam rules (E3).

    `r["accept_fn"]` (zero-arg → PredicateResult) wins when injected; a LIVE run with no
    seam resolves `pred_operator_accept` with the SAME runner dict + config the other
    predicates use (per-key live defaults, no second config read); a HERMETIC run with no
    seam is a plain INDETERMINATE "no operator-accept on head" — never the live `gh`.
    """
    from deterministic_gate import GateVerdict, PredicateResult  # lazy: late-cycle pair

    seam = (r or {}).get("accept_fn")
    if seam is not None:
        return lambda: seam()
    if running_live:
        return lambda: pred_operator_accept(pr_url, head_oid, runners=r, config=config)
    return lambda: PredicateResult("operator_accept", GateVerdict.INDETERMINATE,
                                   NO_ACCEPT_DETAIL)


def proof_or_accept(proof_fn, accept_fn):
    """The proof-or-accept fold for the gate's `review_proof_on_head` slot (E3).

    Both args are zero-arg thunks; the return is one, producing the slot's result:
      proof PASS       → the proof result VERBATIM (the accept is never consulted)
      else accept PASS → PASS under the proof slot's NAME, the accept's detail VERBATIM
                         (it starts "operator-accept by <login> on <sha7>: <reason>" —
                         the prefix task 11.4's land.py keys the accept line on)
      else             → the proof result + "; no operator-accept on head"

    The accept stands in for THIS slot only; every other predicate (human approval above
    all) is untouched and still required. Total and fail-closed: a raising side is an
    unprovable observation — never a raise, never PASS.
    """
    from deterministic_gate import GateVerdict, PredicateResult  # lazy: late-cycle pair

    def _fold():
        proof = None
        try:
            proof = proof_fn()
            if proof.verdict == GateVerdict.PASS:
                return proof
        except Exception:
            proof = None
        try:
            accept = accept_fn()
            if accept.verdict == GateVerdict.PASS:
                return PredicateResult(
                    proof.name if proof else "review_proof_on_head",
                    GateVerdict.PASS, accept.detail)
        except Exception:
            pass
        if proof is None:
            proof = PredicateResult("review_proof_on_head", GateVerdict.INDETERMINATE,
                                    NO_ACCEPT_DETAIL)
        return PredicateResult(proof.name, GateVerdict.INDETERMINATE,
                               f"{proof.detail}; {NO_ACCEPT_DETAIL}")

    return _fold


def main(argv=None) -> int:
    """`operator_accept.py check --pr-url U --head SHA [--repo DIR]`.

    exit 0 PASS / 1 not proven / 2 Gitea (the review-loop forge adapter has no
    native-review body to read — the reason is printed, never a silent 1).
    """
    parser = argparse.ArgumentParser(
        prog="operator_accept.py",
        description="Check for an operator-accept on a PR head.")
    parser.add_argument("command", choices=["check"])
    parser.add_argument("--pr-url", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--repo", default=".",
                        help="repo root whose origin/config decide the forge (default .)")
    args = parser.parse_args(argv)

    import forge  # noqa: E402 — in _shared/ beside this file

    info = forge.resolve(args.repo)
    if info.kind == "gitea":
        print(GITEA_LINE)
        return 2

    from deterministic_gate import GateVerdict  # lazy: late-cycle import pair

    result = pred_operator_accept(args.pr_url, args.head,
                                  config=forge._read_config(args.repo))
    print(result.detail)
    return 0 if result.verdict is GateVerdict.PASS else 1


if __name__ == "__main__":
    sys.exit(main())
