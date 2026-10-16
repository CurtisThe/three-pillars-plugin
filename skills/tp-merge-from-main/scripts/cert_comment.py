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

import sys
from pathlib import Path
from urllib.parse import urlparse

# `automation_identity` lives in the sibling `_shared` dir; put it on the path so a script-path
# import (from this script's own directory) resolves it.
_SHARED = Path(__file__).resolve().parents[2] / "_shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from automation_identity import DISCOVER, run_gh_write  # noqa: E402


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


def format_handres_cert_comment(pre_sha, post_sha, handres_files, *,
                                allowlist_version="v1") -> str:
    """The living-doc-hand-resolution sibling of `format_cert_comment` (design
    `livingdoc-handres-preserves-approval`). Posted by `/tp-merge-from-main` step 7 when the
    just-created base-sync DEFERRED >=1 living-doc file to the human (the deferred set filtered
    through `living_doc_carry.is_living_doc_carry_path`). Audit-only, **ZERO gate authority** --
    the gate (`base_sync_cert.find_certified_anchor`) re-derives the carried K from git objects
    and NEVER reads this comment; a forged/absent/wrong-author copy changes no verdict (same
    guarantee + attack-5 pin as `format_cert_comment`). `handres_files` render sorted/joined."""
    files_str = ", ".join(sorted(handres_files))
    return (
        f"<sub>basesync-cert.v1: pre `{pre_sha}` · post `{post_sha}` · "
        f"allowlist {allowlist_version} · classes [living-doc-handres] · "
        f"handres-files [{files_str}]</sub>"
    )


def _pr_url_parts(pr_url: str) -> tuple[str, str, str]:
    """https://<host>/{owner}/{repo}/pull/{n} -> (owner, repo, number)."""
    parts = [p for p in urlparse(pr_url).path.split("/") if p]
    if len(parts) < 4 or parts[2] != "pull" or not parts[3].isdigit():
        raise ValueError(
            f"pr_url must look like .../{{owner}}/{{repo}}/pull/{{n}}, got: {pr_url!r}"
        )
    return parts[0], parts[1], parts[3]


def _default_run_gh(pr_url: str, body: str, *, config=DISCOVER, runner=None,
                    token_runner=None) -> bool:
    """Post `body` as an issue comment via the REST path (never `gh pr comment`/edit).

    The write runs as the configured automation account (`automation_identity.run_gh_write`,
    which discovers the repo config by default); an unavailable bot raises `BotAuthUnavailable`
    before anything is posted. `config=None` is the plain ambient call."""
    owner, repo, number = _pr_url_parts(pr_url)
    result = run_gh_write(
        ["gh", "api", f"repos/{owner}/{repo}/issues/{number}/comments", "-f", f"body={body}"],
        config=config,
        runner=runner,
        token_runner=token_runner,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def post_cert_comment(pr_url, body, *, run_gh=None, config=DISCOVER) -> bool:
    """Best-effort post of the producer breadcrumb. NEVER raises -- a failure to post
    (bad url, gh not authenticated, an unavailable bot account, network error, an injected
    failing `run_gh`) is logged and ignored by the caller (`/tp-merge-from-main` step 7); the
    gate never reads this comment, so a failed post has ZERO effect on any verdict. An
    unavailable bot returns False with nothing posted (never a post as the ambient login)."""
    poster = run_gh or (lambda url, text: _default_run_gh(url, text, config=config))
    try:
        return bool(poster(pr_url, body))
    except Exception:
        return False
