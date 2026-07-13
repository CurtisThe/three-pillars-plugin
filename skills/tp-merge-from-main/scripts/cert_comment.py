"""cert_comment.py -- the `basesync-cert.v1` producer breadcrumb (audit-only).

`/tp-merge-from-main` step 7 posts this comment to the PR after a fully-auto-resolved
base-sync merge is pushed. It is a human-audit trail ONLY: the deterministic gate's
carry (`base_sync_cert.find_certified_anchor`) NEVER reads this comment -- anchor
discovery is the pure git first-parent walk over `certify_link`-checked merges,
re-derived from git objects alone. A forged, wrong-author, or deleted copy of this
comment cannot change any gate verdict (pinned by
`test_base_sync_cert_attacks.py::test_attack5_*`, task 7.4).

The envelope word `basesync-cert.v1:` is lexically DISJOINT from the proof-of-review
digest's `proof: base` envelope (`review_proof._DIGEST_HEAD_RE` /
`review_proof._DEGRADED_RE`) -- neither regex can ever match the other's body
(`test_cert_comment.py` re-asserts this locally, mirroring task 7.4's cross-module
pin, so a change to either format is caught in both places).

See `three-pillars-docs/completed-tp-designs/approval-survives-safe-base-sync/detailed-design.md`
(Producer breadcrumb section).
"""
from __future__ import annotations

import subprocess
from urllib.parse import urlparse


def format_cert_comment(pre_sha, post_sha, resolved_classes, *, allowlist_version="v1") -> str:
    """Format the audit-only producer breadcrumb. ZERO gate authority -- see module
    docstring. `resolved_classes` is caller-derived (the Phase-1 deviation:
    `merge_driver.resolve_living_doc`'s narrow `(status, merged_text)` return no
    longer populates `FileOutcome.resolved_classes`, so the caller supplies the
    list directly, not read off the resolver outcome)."""
    classes_str = ", ".join(resolved_classes)
    return (
        f"<sub>basesync-cert.v1: pre `{pre_sha}` · post `{post_sha}` · "
        f"allowlist {allowlist_version} · classes [{classes_str}]</sub>"
    )


def _pr_url_parts(pr_url: str) -> tuple[str, str, str]:
    """https://<host>/{owner}/{repo}/pull/{n} -> (owner, repo, number)."""
    parts = [p for p in urlparse(pr_url).path.split("/") if p]
    if len(parts) < 4 or parts[2] != "pull" or not parts[3].isdigit():
        raise ValueError(
            f"pr_url must look like .../{{owner}}/{{repo}}/pull/{{n}}, got: {pr_url!r}"
        )
    return parts[0], parts[1], parts[3]


def _default_run_gh(pr_url: str, body: str) -> bool:
    """Post `body` as an issue comment via the REST path (never `gh pr comment`/edit)."""
    owner, repo, number = _pr_url_parts(pr_url)
    result = subprocess.run(
        ["gh", "api", f"repos/{owner}/{repo}/issues/{number}/comments", "-f", f"body={body}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def post_cert_comment(pr_url, body, *, run_gh=None) -> bool:
    """Best-effort post of the producer breadcrumb. NEVER raises -- a failure to post
    (bad url, gh not authenticated, network error, an injected failing `run_gh`) is
    logged and ignored by the caller (`/tp-merge-from-main` step 7); the gate never
    reads this comment, so a failed post has ZERO effect on any verdict."""
    poster = run_gh or _default_run_gh
    try:
        return bool(poster(pr_url, body))
    except Exception:
        return False
