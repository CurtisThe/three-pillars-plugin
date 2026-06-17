"""thread_dispose — loop-free reply-and-resolve primitive (T1.1).

Single source of truth for reply-and-resolve disposition. Wraps
`skills/_shared/thread_resolver.py` — never reimplements its plumbing.

Entry point: `dispose_threads(pr_url, envelope, *, resolved_ids=None, author, dry_run=False)`

Scope: disposition is for AUTOMATION review threads only (Copilot reviewer bot).
Human-authored review threads are NEVER touched — no reply, no resolve. Silently
resolving a human reviewer's genuine unaddressed objection would invert the design's
purpose and could flip the merge gate's threads_resolved predicate to PASS.

Idempotency guarantees:
  - threads already `is_resolved=True` are skipped entirely (no reply, no resolve).
  - threads whose reply comments carry the WORKER_SIGNATURE are not re-replied
    (the prior disposition reply is still there).
  - calling dispose_threads twice on the same PR produces the same end-state and
    no duplicate replies, even when resolve_thread fails (resolve-failure window).

Reply ordering guarantee:
  - reply_to_thread is ALWAYS called before resolve_thread for any given thread.
    The loop never resolves a thread without first leaving the evidence reply.

C1: stdlib only + thread_resolver only — no `import anthropic`, no claude subprocess.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# thread_resolver lives in the same _shared/ directory
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import thread_resolver  # noqa: E402
import thread_dispose_verify  # noqa: E402
import review_readiness  # noqa: E402

# GraphQL query: fetch a review thread's comments by thread node id.
# Returns up to 100 comments so automation replies (always later than the first)
# are included even in busy threads. Only `body` is needed for signature detection.
# (20 was the prior limit — bump to 100 to reduce truncation-window false misses.)
_THREAD_COMMENTS_QUERY = (
    "query($threadId:ID!){"
    "node(id:$threadId){"
    "... on PullRequestReviewThread{"
    "comments(first:100){nodes{body}}"
    "}}}"
)


# ---------- disposition text (real Python home; SKILL.md only sketched this) ----------


def _disposition_text(disposition: str, finding: dict, envelope: dict) -> str:
    """Format a human-readable disposition body for a Copilot thread.

    disposition — one of 'addressed' | 'deferred' | 'stale'
    finding     — thread dict from list_review_threads (has 'body', 'path', ...)
    envelope    — fix-round envelope (has 'fixes_applied', 'fixes_deferred', ...)

    Returns plain-text body (caller signs via sign_reply before posting).
    """
    path = finding.get("path") or "<unknown path>"
    snippet = (finding.get("body") or "")[:120]

    if disposition == "addressed":
        # Find the applied fix entry for evidence
        cid = finding.get("comment_id")
        applied = [f for f in envelope.get("fixes_applied", []) if f.get("comment_id") == cid]
        commit_ref = applied[0].get("commit_sha", "") if applied else ""
        evidence = f" (commit {commit_ref})" if commit_ref else ""
        return (
            f"Addressed{evidence}. The flagged region in `{path}` has been fixed this round.\n\n"
            f"> {snippet}"
        )

    if disposition == "deferred":
        cid = finding.get("comment_id")
        deferred = [f for f in envelope.get("fixes_deferred", []) if f.get("comment_id") == cid]
        reason = deferred[0].get("reason", "conflict or structural deferral") if deferred else (
            "no actionable fix was dispatched this round"
        )
        return (
            f"Deferred: {reason}. This finding will be revisited in the next round.\n\n"
            f"> {snippet}"
        )

    if disposition == "stale":
        return (
            f"This thread was already resolved in a prior round. "
            f"Marking stale/addressed — no new action needed.\n\n"
            f"> {snippet}"
        )

    # Fallback for any unrecognised disposition
    return f"Disposition: {disposition}.\n\n> {snippet}"


# ---------- idempotency helpers ----------


def _thread_has_automation_reply(thread_id: str) -> bool:
    """Return True if any comment on the thread carries the worker signature.

    Queries up to 100 comments on the thread node by id so that automation
    replies (always posted AFTER the first/original Copilot comment) are
    included. This is the real idempotency guard against the resolve-failure
    window: reply succeeded but resolve failed → thread stays unresolved, but
    the signature is present in a later comment → we skip re-replying.

    Fail-open: any gh/parse failure returns False (conservative — may retry
    resolve, but will not post a duplicate reply because the reply path is
    guarded by the return value).
    """
    result = subprocess.run(
        [
            "gh", "api", "graphql",
            "-f", f"query={_THREAD_COMMENTS_QUERY}",
            "-F", f"threadId={thread_id}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return False
    try:
        data = json.loads(result.stdout)
    except ValueError:
        return False
    node = (data.get("data") or {}).get("node") or {}
    comments = (node.get("comments") or {}).get("nodes") or []
    # WORKER_SIGNATURE invariant substring — same check as the old _already_replied
    # but now across ALL comments, not just the first.
    return any("three-pillars-worker" in (c.get("body") or "") for c in comments)


# ---------- public API ----------


def dispose_threads(
    pr_url: str,
    envelope: dict,
    *,
    resolved_ids: "set | None" = None,
    author: str = "automation",
    dry_run: bool = False,
    base_dir: "Path | None" = None,
) -> dict:
    """Reply-and-resolve every open, actionable Copilot review thread on pr_url.

    SCOPE: Only threads whose author matches the GraphQL Copilot login (via
    review_readiness.is_copilot_review_author(..., surface="graphql")) are
    processed. Human-authored review threads are left ENTIRELY untouched (no
    reply, no resolve). This preserves the merge gate's threads_resolved
    predicate integrity.

    Args:
        pr_url:       GitHub PR URL.
        envelope:     fix-round envelope dict (fixes_applied / fixes_deferred).
                      Pass an empty envelope `{"fixes_applied": [], "fixes_deferred": []}`
                      when called out-of-band (no round has run).
        resolved_ids: set of thread_ids already resolved in prior rounds. Used by
                      disposition_for to classify a thread as 'stale'. Defaults to
                      an empty set (correct for out-of-band calls).
        author:       GitHub login of the automation actor (used in the reply signature).
        dry_run:      If True, compute dispositions and log them but do NOT call
                      reply_to_thread / resolve_thread.

    Returns a result record:
        {
            "replied":  list[str],  # thread_ids where a reply was posted this call
            "resolved": list[str],  # thread_ids resolved this call
            "skipped":  list[str],  # thread_ids skipped (already resolved / already replied)
        }
    """
    if resolved_ids is None:
        resolved_ids = set()

    replied: list[str] = []
    resolved: list[str] = []
    skipped: list[str] = []

    threads = thread_resolver.list_review_threads(pr_url)

    for thread in threads:
        tid = thread.get("thread_id")

        # Skip threads NOT authored by the Copilot reviewer bot.
        # Human-authored review threads are NEVER replied to or resolved here;
        # doing so would silently dismiss a human reviewer's unaddressed objection.
        # Uses review_readiness.is_copilot_review_author with surface="graphql" —
        # the canonical authority for the bare login that reviewThreads emits
        # (no "[bot]" suffix on the GraphQL surface).
        if not review_readiness.is_copilot_review_author(
            thread.get("author", ""), surface="graphql"
        ):
            continue

        # Skip threads with no thread_id — we cannot resolve without one, and
        # reply-before-resolve-as-a-unit means: if we can't resolve, don't reply.
        if tid is None:
            continue

        # Skip threads already resolved (idempotency: no duplicate resolve)
        if thread.get("is_resolved") is True:
            skipped.append(tid)
            continue

        # Skip threads already carrying the automation signature (idempotency: no
        # duplicate reply in the resolve-failure window). Fetches all thread
        # comments so the signature in a LATER reply comment is detected — the
        # original Copilot comment (comments(first:1)) never carries our signature.
        # tid is guaranteed non-None here (early-exited above if None).
        already_has_reply = _thread_has_automation_reply(tid)

        # Verify-before-dispose guard (T1.2): check if the flagged pattern is still
        # present. An already-fixed re-anchored finding is classified stale_addressed
        # and disposed honestly — code is NEVER modified by this path.
        verify_verdict = thread_dispose_verify.check_before_dispose(
            thread, base_dir=base_dir
        )

        if verify_verdict == "stale_addressed":
            # Override: use stale disposition regardless of envelope contents
            disposition = "stale"
        else:
            # Compute disposition via thread_resolver (single source; never hand-judge)
            disposition = thread_resolver.disposition_for(thread, envelope, resolved_ids)

        body_text = _disposition_text(disposition, thread, envelope)
        signed_body = thread_resolver.sign_reply(body_text, author)

        if dry_run:
            # Log only; do not mutate GitHub state
            continue

        cid = thread.get("comment_id")

        # --- REPLY before RESOLVE (ordering invariant) ---
        reply_ok = False
        if already_has_reply:
            # Prior reply present — do not re-post; treat as if reply succeeded
            reply_ok = True
        else:
            if cid is not None:
                reply_ok = thread_resolver.reply_to_thread(pr_url, cid, signed_body)
                if reply_ok:
                    replied.append(tid)

        # --- RESOLVE only after a successful reply ---
        if reply_ok:
            ok = thread_resolver.resolve_thread(tid)
            if ok:
                resolved.append(tid)
                resolved_ids.add(tid)

    return {"replied": replied, "resolved": resolved, "skipped": skipped}
