"""proof_post.py — post the review-proof digest, then read its author back.

design: review-proof-ambient-gh-identity

`post_proof_checked` posts the digest through `review_merge.post_codereview_comment` (which
runs the write as the configured automation account, so the identity is picked by the helper
and never by a `GH_TOKEN` prefix in the calling shell), then reads the PR comments with the
gate's own reader and checks the digest's author against the trust set the gate will compute
(`review_proof._trusted_digest_authors`). An author outside that set yields
`proof-author-untrusted`, so the round learns about it now and not when `/tp-merge` refuses.

Digest detection reuses `review_proof._DIGEST_HEAD_RE` / `_DEGRADED_RE`: no second parser.
A read-back that cannot find a digest is `ok` with `author: None`: the converge oracle
(`convergence_proof.non_degraded_proof_on_head`) still fails closed on a missing proof.

Statuses: `ok` · `post-failed` · `bot-auth-unavailable` (a configured bot whose token cannot
be fetched, or an unusable config; nothing was posted) · `proof-author-untrusted`. No token
ever reaches a returned value. Stdlib only.

CLI (a hand-driven round tail): `proof_post.py --pr-url U --head H --findings f.json
--digest-file d.txt --config .three-pillars/config.json` prints one JSON line, exit 0 on `ok`,
3 otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED = _HERE.parent.parent / "_shared"
for _p in (_HERE, _SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import review_merge  # noqa: E402
import review_proof  # noqa: E402
from automation_identity import BotAuthUnavailable  # noqa: E402

# The identity stops: a terminal of their own, never read as §D8 evidence-complete.
IDENTITY_STOPS = frozenset({"bot-auth-unavailable", "proof-author-untrusted"})

_EXIT_OK = 0
_EXIT_BLOCKED = 3


def _digest_author(items, head: str) -> "str | None":
    """Login of the LAST comment carrying a non-degraded digest for `head`, else None.

    Matches the gate's per-line rule (`proof_comment_on_head`): a DEGRADED digest is not proof,
    the parsed head must equal `head` exactly, and an authorless item is ignored.
    """
    found = None
    for item in items:
        if not isinstance(item, dict):
            continue
        author, body = item.get("author"), item.get("body")
        if not isinstance(author, str) or not author:
            continue
        for line in (body if isinstance(body, str) else str(body or "")).splitlines():
            if review_proof._DEGRADED_RE.search(line):
                continue
            m = review_proof._DIGEST_HEAD_RE.search(line)
            if m and m.group(1) == head:
                found = author
                break
    return found


def _read_back_author(pr_url, head, comments_fn) -> "str | None":
    try:
        items = (comments_fn or review_proof._default_comments_fn)(pr_url)
        return _digest_author(items, str(head)) if isinstance(items, list) else None
    except Exception:  # noqa: BLE001 — unreadable: ok/None, the oracle fails closed
        return None


def post_proof_checked(pr_url, findings, *, head, digest, config, post_fn=None,
                       comments_fn=None, self_login_fn=None) -> dict:
    """Post the proof digest as the configured automation account, then verify its author.

    Returns `{"status": ..., "author": <login or None>, ...}` (module docstring).
    """
    try:
        posted = review_merge.post_codereview_comment(
            pr_url, findings, head_sha=head, digest=digest, post_fn=post_fn, config=config)
    except BotAuthUnavailable as exc:
        return {"status": "bot-auth-unavailable", "author": None, "detail": str(exc)}
    if not posted:
        return {"status": "post-failed", "author": None}
    author = _read_back_author(pr_url, head, comments_fn)
    if author is None:
        return {"status": "ok", "author": None}
    try:
        trusted = review_proof._trusted_digest_authors(config, self_login_fn)
    except BotAuthUnavailable as exc:
        return {"status": "bot-auth-unavailable", "author": author, "detail": str(exc)}
    if author.lower() in trusted:
        return {"status": "ok", "author": author}
    return {"status": "proof-author-untrusted", "author": author, "trusted": sorted(trusted)}


def _parse_args(argv):
    p = argparse.ArgumentParser(
        prog="proof_post.py",
        description="Post the review-proof digest as the configured automation account, "
                    "then read its author back against the gate's trust set.")
    p.add_argument("--pr-url", dest="pr_url", required=True, help="PR URL")
    p.add_argument("--head", required=True, help="PR head SHA (full) the digest binds to")
    p.add_argument("--findings", required=True,
                   help="path to a JSON list of findings ([] for a clean round)")
    p.add_argument("--digest-file", dest="digest_file", required=True,
                   help="path to a text file holding one format_proof_digest line")
    p.add_argument("--config", required=True, help="path to .three-pillars/config.json")
    return p.parse_args(argv)


def _finish(result: dict) -> int:
    print(json.dumps(result))
    return _EXIT_OK if result["status"] == "ok" else _EXIT_BLOCKED


def main(argv=None, *, seams=None) -> int:
    """CLI entry. `seams` (tests) may carry `post_fn`, `comments_fn`, `self_login_fn`."""
    args = _parse_args(argv)
    try:
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError("the config is not a JSON object")
    except Exception as exc:  # noqa: BLE001 — a configured bot cannot be ruled out: refuse
        return _finish({"status": "bot-auth-unavailable", "author": None,
                        "detail": f"could not read config {args.config!r}: {exc}"})
    try:
        findings = json.loads(Path(args.findings).read_text(encoding="utf-8"))
        digest = Path(args.digest_file).read_text(encoding="utf-8").strip()
        if not isinstance(findings, list) or not digest:
            raise ValueError("--findings must hold a JSON list and --digest-file a digest line")
    except Exception as exc:  # noqa: BLE001
        return _finish({"status": "bad-input", "author": None, "detail": str(exc)})
    return _finish(post_proof_checked(
        args.pr_url, findings, head=args.head, digest=digest, config=config, **(seams or {})))


if __name__ == "__main__":
    sys.exit(main())
