"""human_approval_review — the APPROVED-PR-review path of the human-approval gate.

stdlib-only (C1 invariant: no `import anthropic`, no `subprocess.run(["claude", ...])`).
This module owns the *review* satisfaction path — the SOLE mechanism behind
`human_approval.human_approved_on_head` after retire-approval-tags removed the SHA-tagged-label
path (Path A). A native GitHub `APPROVED` review carries an
immutable, server-set `commit_id`, so currency is a direct `commit_id == headRefOid` check —
the field GitHub never populates on `labeled` timeline events (which is why the label had to
smuggle the head SHA into its NAME). See
`three-pillars-docs/completed-tp-designs/review-as-human-approval/design.md` (Behaviors) and
`detailed-design.md` (Decisions D2–D6).

Identity is decided by REUSING `human_approval`'s guards verbatim against the review author:
the REST review `user` object carries `login` + `type` exactly like a timeline `actor`, so a
`{"actor": review["user"]}` adapter lets `_actor_is_human` / `_approver_not_automation` apply
unchanged — no parallel automation-rejection logic.

Every helper is TOTAL and fail-CLOSED: any malformed/alien input yields the un-satisfied
result (False / None), never an exception.
"""

from __future__ import annotations

import sys
from pathlib import Path

# ---- sys.path: ensure _shared/ is importable so sibling modules resolve ----
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import human_approval  # noqa: E402 — in _shared/ beside this file


# ============================================================
# Task 1.1: _review_current_on_head (currency, load-bearing)
# ============================================================


def _review_current_on_head(review, head) -> bool:
    """Load-bearing currency conjunct for the review path.

    current ⟺ review["commit_id"] (non-empty str) case-folds-equal to
    head["headRefOid"] (non-empty str). The review's `commit_id` is the IMMUTABLE,
    server-set field GitHub populates on review submission — the exact binding the
    label's `commit_id: null` could never provide. A real content change leaves the
    review pinned to the old SHA (non-current → fail-closed); a diff-unchanged no-op
    push is carried forward by GitHub re-pointing `commit_id` to the new head
    (server-side, validated on spike PR #93).

    Case-folded (GitHub returns lowercase hex; a typed value may be uppercase).
    Total / fail-closed: a non-dict review/head, missing/empty/non-str `commit_id`
    or `headRefOid`, or any alien input → False, never raises.
    """
    if not isinstance(review, dict) or not isinstance(head, dict):
        return False
    commit_id = review.get("commit_id")
    if not isinstance(commit_id, str) or not commit_id:
        return False
    head_oid = head.get("headRefOid")
    if not isinstance(head_oid, str) or not head_oid:
        return False
    return commit_id.lower() == head_oid.lower()


# ============================================================
# Task 1.2: _review_author_is_human (reuse identity guards verbatim)
# ============================================================


def _review_author_is_human(review, automation) -> bool:
    """The review's author clears the SAME identity floor the label path uses.

    The REST `pulls/<n>/reviews` `user` object carries `login` + `type` exactly like
    a `labeled`-event `actor`, so we ADAPT the shape (`{"actor": review["user"]}`) and
    reuse `human_approval._actor_is_human` + `_approver_not_automation` VERBATIM — no
    second, divergent automation-rejection path. This rejects: a `type=="Bot"` actor
    (App-installation tokens), a `[bot]`-suffix login (catch-all backstop), any login in
    the `automation` set (configured/self/known bots), and an empty/missing login.

    Total / fail-closed: a non-dict review, a missing/None `user` (adapter → `{"actor":
    None}`, backstopped by the guard's own `isinstance(actor, dict)` check) → False.
    """
    if not isinstance(review, dict):
        return False
    adapted = {"actor": review.get("user")}
    return bool(
        human_approval._actor_is_human(adapted, automation)
        and human_approval._approver_not_automation(adapted, automation)
    )


# ============================================================
# Task 1.3: latest_human_review (filter-to-human, then most-recent)
# ============================================================


def latest_human_review(reviews, automation):
    """The most-recent NON-AUTOMATION-HUMAN review, or None.

    Filter-to-human-THEN-latest (mirrors review_readiness.latest_copilot_review with the
    author class inverted): keep only reviews whose author clears
    `_review_author_is_human`, then return `max(...)` by `submitted_at`. Filtering BEFORE
    the timestamp selection is load-bearing — a trailing bot COMMENTED review later than a
    human APPROVED must NOT become "the latest review", so it cannot clobber a standing
    human approval. A human's own later CHANGES_REQUESTED IS selected (it is human), and
    the state check downstream (`review_path_satisfied`) then fails closed.

    Total / fail-closed: a non-list `reviews`, malformed/alien entries (skipped by the
    human filter), or no human review → None, never raises. `max` is stable — on a
    `submitted_at` tie it returns the first (lowest-index) human review.
    """
    if not isinstance(reviews, list):
        return None
    humans = [r for r in reviews if _review_author_is_human(r, automation)]
    if not humans:
        return None
    return max(humans, key=lambda r: r.get("submitted_at", ""))


# ============================================================
# Task 1.4: review_path_satisfied (the review-path entry point)
# ============================================================


def review_path_satisfied(reviews, head, *, automation) -> bool:
    """True ⟺ a non-automation human's LATEST review is APPROVED and current on head.

    Composes the three review-path conjuncts:
      1. latest = latest_human_review(reviews, automation)   (filter-to-human, then latest)
      2. latest.state == "APPROVED"                          (the approval itself)
      3. _review_current_on_head(latest, head)               (commit_id == headRefOid)

    A later human CHANGES_REQUESTED/COMMENTED supersedes an earlier APPROVED (it becomes
    the latest human review and fails conjunct 2); a real content change leaves the review
    pinned to the old SHA and fails conjunct 3 (fail-closed).

    NOTE: the diff-unchanged no-op-push carry-forward (an empty/whitespace/rebase push that
    leaves the tree identical) is SERVER-SIDE — GitHub re-points the review's `commit_id` to
    the new head before the gate ever fetches it (validated on spike PR #93). It is therefore
    NOT unit-testable here (an injected dict is pre-corrected by construction); it is covered
    by the live-gate regression. No unit fixture is added for it by design.

    Total / fail-closed: no human review, non-APPROVED latest, stale/missing currency, or any
    malformed/alien input → False, never raises.
    """
    try:
        latest = latest_human_review(reviews, automation)
        if latest is None:
            return False
        return latest.get("state") == "APPROVED" and _review_current_on_head(latest, head)
    except Exception:
        return False


# ============================================================
# Task 6.2: carried_review_approval (approval-survives-safe-base-sync consumer 1)
# ============================================================


def carried_review_approval(reviews, head, *, automation, config, repo_root,
                            base_ref, run_git=None) -> "tuple[bool, str]":
    """The carry-aware sibling of `review_path_satisfied` — called ONLY on a currency
    MISS (the caller already tried `review_path_satisfied` and it failed).

    REUSES every existing identity/state guard verbatim, none relaxed:
      1. latest = latest_human_review(reviews, automation)   — filter-to-human, then latest
      2. latest["state"] == "APPROVED"                       — the approval itself
      3. anchor = latest["commit_id"] is a non-empty str      — the review's pinned SHA
      4. head["headRefOid"] is a non-empty str
      5. anchor != head_oid (case-folded)                     — not a carry, currency's job

    Only once ALL FIVE hold does this delegate to `base_sync_cert.certified_noop_chain`
    (the independent-oracle-gated no-op-chain walk) — an automation-authored review, a
    non-APPROVED latest, or an unresolvable anchor/head NEVER reaches the chain walk, and
    returns `(False, "")` (no carry was attempted, so no reason to report). Only a REAL
    chain-walk attempt that then refuses carries a non-empty `reason` — this is the
    caller's (`human_approval.approved_on_head_result`) signal for whether to append
    `"; carry: <reason>"` to the gate's remediation detail.

    Success: `(True, "approval carried across N certified base-sync merge(s) (anchor
    <sha7>)")`. Total — never raises; any malformed input or internal error → `(False, "")`.
    """
    try:
        latest = latest_human_review(reviews, automation)
        if latest is None:
            return False, ""
        if latest.get("state") != "APPROVED":
            return False, ""
        anchor = latest.get("commit_id")
        if not isinstance(anchor, str) or not anchor:
            return False, ""
        if not isinstance(head, dict):
            return False, ""
        head_oid = head.get("headRefOid")
        if not isinstance(head_oid, str) or not head_oid:
            return False, ""
        if anchor.lower() == head_oid.lower():
            return False, ""   # not a carry — review_path_satisfied's job

        import base_sync_cert  # noqa: E402 — in _shared/ beside this file

        result = base_sync_cert.certified_noop_chain(
            repo_root, anchor, head_oid, base_ref=base_ref,
            max_links=base_sync_cert.carry_max_chain(config), run_git=run_git,
        )
        if result.certified:
            sha7 = (result.anchor or anchor)[:7]
            return True, (
                f"approval carried across {result.links} certified base-sync "
                f"merge(s) (anchor {sha7})"
            )
        return False, result.reason
    except Exception:
        return False, ""


def resolve_carry(pr_url, reviews, head, *, automation, config, runners) -> "tuple[bool, str]":
    """Carry-seam resolution, extracted out of `human_approval.approved_on_head_result`
    to keep that file under the 350-line soft-warn (plan.md task 6.1's named escape
    hatch). Called unconditionally on a currency MISS; checks `carry_enabled(config)`
    itself FIRST so a config-off caller pays zero cost beyond that one cheap check.

    Resolves, in order: `repo_root` (runners["carry_repo_root"] or
    `project_root.find_project_root()`; unresolvable → no carry); `base_ref`
    (runners["derive_base_ref_fn"](pr_url) or `diff_balloon_guard.derive_base_ref(pr_url)`;
    unresolvable → no carry); `run_git` (runners["run_git"], `None` → the chain walk's own
    live default). Delegates to `carried_review_approval`. Total, never raises; any
    unresolvable seam → `(False, "")` (no carry ATTEMPTED, so no reason to report —
    distinct from an attempted-and-refused chain walk, which carries a `ChainResult`
    reason string).
    """
    try:
        import base_sync_cert  # noqa: E402 — in _shared/ beside this file

        if not base_sync_cert.carry_enabled(config):
            return False, ""

        repo_root = runners.get("carry_repo_root")
        if repo_root is None:
            import project_root  # noqa: E402 — in _shared/ beside this file
            repo_root = project_root.find_project_root()
        if repo_root is None:
            return False, ""

        derive_base_ref_fn = runners.get("derive_base_ref_fn")
        if derive_base_ref_fn is not None:
            base_ref = derive_base_ref_fn(pr_url)
        else:
            import diff_balloon_guard  # noqa: E402 — in _shared/ beside this file
            base_ref = diff_balloon_guard.derive_base_ref(pr_url)
        if not base_ref:
            return False, ""

        run_git = runners.get("run_git")

        return carried_review_approval(
            reviews, head, automation=automation, config=config,
            repo_root=repo_root, base_ref=base_ref, run_git=run_git,
        )
    except Exception:
        return False, ""
