"""thread_resolver — reply-and-resolve GitHub review threads (Enhancement 1).

Each `/tp-pr-iterate` round must, for every Copilot review comment: post a
worker-signed disposition reply (addressed / stale / deferred + evidence) and
THEN resolve the thread. Copilot re-posts comments anchored to unchanged diff
lines every round, so without reply-and-resolve the loop re-litigates
already-fixed items forever and the new-vs-stale signal is unusable.

Two GitHub ids are in play and are NOT interchangeable:
  - `thread_id`  — the GraphQL review-thread node id. Used to RESOLVE
    (`resolveReviewThread` mutation).
  - `comment_id` — the REST comment databaseId. Used to REPLY
    (`POST /pulls/{n}/comments/{cid}/replies`).

C1: this helper is plumbing only — `gh api` / `gh api graphql` subprocesses.
No `import anthropic`, no `subprocess.run(["claude", …])`. The reply-BEFORE-
resolve ordering is owned by SKILL.md prose (the two functions are separate so
the orchestration layer enforces and tests the order); the worker never
resolves a thread without first leaving the evidence reply.
"""

from __future__ import annotations

import json
import re
import subprocess

# The PR replies/threads are posted under the user's own `gh` token, so the
# GitHub *actor* is the user. The worker identity is a content-level signature
# — paralleling fix_round's GIT_COMMITTER_EMAIL=orchestrator+{local}@{domain}
# override — so a reader can tell a worker reply from the human author's.
WORKER_SIGNATURE = "🤖 three-pillars-worker (on behalf of @{author})"

_PR_URL_RE = re.compile(r"https?://github\.com/([^/]+)/([^/]+)/(?:pull|issues)/(\d+)")

_THREADS_QUERY = (
    "query($owner:String!,$repo:String!,$number:Int!){"
    "repository(owner:$owner,name:$repo){"
    "pullRequest(number:$number){"
    "reviewThreads(first:100){nodes{"
    "id isResolved comments(first:1){nodes{databaseId author{login} path body}}"
    "}}}}}"
)

_RESOLVE_MUTATION = (
    "mutation($threadId:ID!){"
    "resolveReviewThread(input:{threadId:$threadId}){thread{isResolved}}}"
)


def _parse_pr_url(pr_url: str) -> tuple[str, str, str]:
    m = _PR_URL_RE.match(pr_url)
    if not m:
        raise ValueError(f"unrecognized GitHub PR URL: {pr_url!r}")
    return m.group(1), m.group(2), m.group(3)


# ---------- worker identity ----------


def sign_reply(body: str, author: str) -> str:
    """Prefix a reply body with the worker signature line + blank line."""
    return f"{WORKER_SIGNATURE.format(author=author)}\n\n{body}"


# ---------- disposition ----------


def disposition_for(finding: dict, envelope: dict, resolved_ids: set) -> str:
    """Derive the disposition for a Copilot finding from the fix-round envelope.

    - 'addressed' — its comment_id is in envelope.fixes_applied[].comment_id
    - 'deferred'  — its comment_id is in envelope.fixes_deferred[].comment_id
    - 'stale'     — its thread_id was already resolved in a prior round
    - else        — 'deferred' (conservative default; never silently 'addressed')
    """
    cid = finding.get("comment_id")
    applied = {f.get("comment_id") for f in envelope.get("fixes_applied", [])}
    deferred = {f.get("comment_id") for f in envelope.get("fixes_deferred", [])}
    if cid is not None and cid in applied:
        return "addressed"
    if cid is not None and cid in deferred:
        return "deferred"
    if finding.get("thread_id") in resolved_ids:
        return "stale"
    return "deferred"


# ---------- GitHub plumbing ----------


def _threads_from_nodes(nodes: list) -> list[dict]:
    """Map GraphQL reviewThreads `nodes` → the public thread-dict shape.

    Shared by the fail-open and fail-closed fetchers so the two never drift.
    Returns [{thread_id, is_resolved, comment_id, path, body, author}].
    """
    out = []
    for n in nodes:
        comments = (n.get("comments") or {}).get("nodes") or [{}]
        c = comments[0] if comments else {}
        out.append(
            {
                "thread_id": n.get("id"),
                "is_resolved": n.get("isResolved", False),
                "comment_id": c.get("databaseId"),
                "path": c.get("path"),
                "body": c.get("body", ""),
                "author": (c.get("author") or {}).get("login", ""),
            }
        )
    return out


def list_review_threads_strict(pr_url: str) -> list[dict]:
    """Every review thread on the PR, via GraphQL — FAIL-CLOSED (RAISES on failure).

    Unlike `list_review_threads` (which swallows every failure to `[]`), this RAISES
    on any condition under which the thread set cannot be PROVEN: a non-zero `gh`
    return, empty stdout, unparsable JSON, or a null `pullRequest` (GraphQL partial
    error / missing PR). The deterministic merge gate calls THIS — via
    `deterministic_gate.fetch_threads_or_none` — so a transient fetch failure folds
    to INDETERMINATE, never an empty-looks-resolved PASS.

    Why this exists: the gate's `fetch_threads_or_none` only returns its fail-closed
    `None` sentinel when its `threads_fn` raises or returns a non-list. Wired to the
    fail-open `list_review_threads`, that wrapper was a production no-op — the live
    fetcher never raised, so a token/rate-limit/network blip collapsed an unresolved
    blocking thread to `[]` and the gate PASSed it. (Audit: H3-defeating fail-open.)

    A genuinely thread-less PR still returns `[]` WITHOUT raising (pullRequest
    present, `reviewThreads.nodes` empty) — empty means "no threads", a proven
    success, not a fetch failure.

    Returns [{thread_id, is_resolved, comment_id, path, body, author}].
    """
    owner, repo, number = _parse_pr_url(pr_url)
    result = subprocess.run(
        [
            "gh", "api", "graphql",
            "-f", f"query={_THREADS_QUERY}",
            "-F", f"owner={owner}",
            "-F", f"repo={repo}",
            "-F", f"number={number}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"gh api graphql failed (rc={result.returncode}): {result.stderr.strip()}"
        )
    if not result.stdout.strip():
        raise RuntimeError("gh api graphql returned empty stdout")
    data = json.loads(result.stdout)  # JSONDecodeError (ValueError subclass) propagates
    # A GraphQL partial-error returns `pullRequest` as JSON null with exit 0. The
    # fail-open variant treats that as `[]` via `or {}`; here it is an UNPROVEN fetch
    # → raise, so the gate cannot read a partial error as a clean zero-thread PR.
    pr = ((data.get("data") or {}).get("repository") or {}).get("pullRequest")
    if pr is None:
        raise RuntimeError(
            "GraphQL returned null pullRequest (partial error or missing PR)"
        )
    nodes = (pr.get("reviewThreads") or {}).get("nodes") or []
    return _threads_from_nodes(nodes)


def list_review_threads(pr_url: str) -> list[dict]:
    """Every review thread on the PR, via GraphQL — FAIL-OPEN (every failure → []).

    Best-effort wrapper used by the `/tp-pr-iterate` loop, which tolerates a
    transient miss and re-polls. The deterministic merge gate must NOT use this — a
    swallowed failure is indistinguishable from a clean zero-thread PR; the gate uses
    `list_review_threads_strict` via `fetch_threads_or_none`.

    The `thread_id` is the GraphQL node id (resolve); `comment_id` is the first
    comment's databaseId (reply) — the two differ.
    Returns [{thread_id, is_resolved, comment_id, path, body, author}].
    """
    try:
        return list_review_threads_strict(pr_url)
    except Exception:
        return []


def reply_to_thread(pr_url: str, comment_id, body: str) -> bool:
    """Post a reply on the review comment thread via REST. Fail-open → False.

    Uses the comment databaseId (`comment_id`), NOT the thread node id. The
    caller signs `body` with `sign_reply` first.
    """
    owner, repo, number = _parse_pr_url(pr_url)
    result = subprocess.run(
        [
            "gh", "api",
            f"repos/{owner}/{repo}/pulls/{number}/comments/{comment_id}/replies",
            "-f", f"body={body}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def resolve_thread(thread_id: str) -> bool:
    """Resolve a review thread via the GraphQL resolveReviewThread mutation.

    Uses the thread node id (`thread_id`), NOT the comment databaseId.
    Fail-open → False. Never `gh pr edit` (broken on this repo).
    """
    result = subprocess.run(
        [
            "gh", "api", "graphql",
            "-f", f"query={_RESOLVE_MUTATION}",
            "-F", f"threadId={thread_id}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0
