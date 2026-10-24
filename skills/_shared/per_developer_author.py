"""per_developer_author.py — the PR author, for `github.per_developer_author: self`.

design: per-developer-automation-account

Under `self` the merge gate also trusts a review-proof digest posted by the PR's own author.
This module reads that author from the human-approval head fetch (one implementation, called
lazily and only under `self`), refuses anyone who is automation, and holds the roster text.
Every failure reads as "no author": the digest is then not trusted, so the gate fails closed.
Stdlib only; nothing here writes to GitHub or touches a token.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


def login_from_head(payload) -> "str | None":
    """The PR author's login from a head payload, or None.

    None when the payload has no usable `author.login`, or the author is automation: `is_bot`,
    an `app/` login, a `[bot]` login, `ghost`, or (lowercased) in the hardcoded automation floor.
    """
    author = payload.get("author") if isinstance(payload, dict) else None
    if not isinstance(author, dict):
        return None
    login = author.get("login")
    if not isinstance(login, str) or not login:
        return None
    import human_approval
    import review_readiness

    low = login.lower()
    floor = review_readiness._REST_COPILOT_LOGINS | human_approval._GITHUB_NATIVE_AUTOMATION
    if (author.get("is_bot") is True or low.startswith("app/") or low.endswith("[bot]")
            or low == "ghost" or low in floor):
        return None
    return login


def pr_author_fn_for(pr_url: str, head_fn=None):
    """A fresh closure returning the PR author login, memoized for its own lifetime.

    No module-level cache. None unless the payload's `isCrossRepository` is exactly `False`
    (a fork PR, or an unknown shape, is never trusted) and on any fetch error.
    """
    memo: list = []

    def author() -> "str | None":
        if memo:
            return memo[0]
        try:
            fetch = head_fn
            if fetch is None:
                import human_approval
                fetch = human_approval._build_live_runners(pr_url)["head_fn"]
            payload = fetch(pr_url)
            login = (login_from_head(payload)
                     if isinstance(payload, dict) and payload.get("isCrossRepository") is False
                     else None)
        except Exception:
            login = None
        memo.append(login)
        return login

    return author


def self_posted_detail(login: str) -> str:
    """The roster detail naming a digest the PR author posted for themselves."""
    return f"self-attested digest by {login} (per_developer_author: self)"


def roster_detail(detail, anchor, head_authors, pr_author, base, carry) -> str:
    """`detail`, or the self-attested text when only the PR author's digest is on `anchor`.

    `anchor` is the PASS head (direct) or the carry anchor; the author must not be in `base` (the
    bot/automation set) and `head_authors[anchor]` must be exactly that author. A carry appends
    the text after `; `. Any error keeps `detail`.
    """
    try:
        author = pr_author.lower() if isinstance(pr_author, str) and pr_author else None
        if author is None or author in base or head_authors.get(anchor) != {author}:
            return detail
        text = self_posted_detail(pr_author)
        return f"{detail}; {text}" if carry else text
    except Exception:
        return detail
