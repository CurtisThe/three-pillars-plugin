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


def list_review_threads(pr_url: str) -> list[dict]:
    """Every review thread on the PR, via GraphQL.

    Returns [{thread_id, is_resolved, comment_id, path, body, author}]. The
    `thread_id` is the GraphQL node id (resolve); `comment_id` is the first
    comment's databaseId (reply) — the two differ.
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
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        data = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return []
    # Null-safe navigation: a GraphQL partial-error returns the key present with
    # a JSON null value (e.g. {"data":{"repository":{"pullRequest":null}}}), so a
    # plain .get(k, {}) yields None, not the default — guard each hop with `or {}`
    # to preserve the fail-open [] contract.
    nodes = (
        ((((data.get("data") or {}).get("repository") or {}).get("pullRequest") or {})
         .get("reviewThreads") or {}).get("nodes")
        or []
    )
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
