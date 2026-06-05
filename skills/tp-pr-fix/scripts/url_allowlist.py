"""url_allowlist — verify a URL resolves to a host on an explicit allowlist.

Used by `/tp-pr-fix` when a PR comment contains a link and the fix-round
needs to decide whether following that link is safe. The check is:

  1. Parse the URL via `urllib.parse.urlparse`. The `netloc` must EXACTLY
     match an entry in the allowlist (no suffix matching — `evil-example.com`
     does NOT match `example.com`).
  2. Probe the URL with a HEAD request. If the server returns a 30x with a
     `Location:` header, the redirect target's netloc must ALSO be on the
     allowlist — otherwise the URL would smuggle the client to an
     off-allowlist host.

Spec deviation pre-approved per [[feedback_test_spec_intent]]:

  plan.md Task 4.3 literal calls for `requests.head(url,
  allow_redirects=False, timeout=5)`, but `requests` is NOT in
  `requirements-dev.txt` (only `pytest>=9.0` and `jsonschema>=4.26`).
  Phase 3 hit the same situation with `psutil` and resolved by using a
  stdlib alternative (parsing `/proc` directly). We do the same here:
  this module is stdlib-only and uses `urllib.request.urlopen` with a
  no-follow-redirects opener built from a custom
  `HTTPRedirectHandler.redirect_request` that returns `None`. That is the
  urllib equivalent of `allow_redirects=False` — the four behavioral
  assertions on the plan (exact netloc match, suffix rejected, 30x
  off-allowlist rejected, no-follow on HEAD) are preserved.

stdlib only — no `requests`, no extra deps. See module docstring of
`skills/_shared/aider_install_check.py` for the same convention.
"""

from __future__ import annotations

import urllib.request
from urllib.error import HTTPError
from urllib.parse import urlparse

# 30x status codes whose `Location` header redirects the client to a
# different URL. 304 (Not Modified) is excluded — it does not redirect.
_REDIRECT_STATUSES: frozenset[int] = frozenset({301, 302, 303, 307, 308})

_TIMEOUT_SECONDS: int = 5


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """HTTPRedirectHandler that disables automatic redirect following.

    Returning `None` from `redirect_request` causes the default opener to
    surface the 30x response itself instead of fetching the `Location`
    target — the urllib equivalent of `requests`'
    `allow_redirects=False`.
    """

    def redirect_request(self, *args, **kwargs):  # noqa: D401 — see class doc
        return None


# Module-local `urlopen` binds to a no-follow-redirects opener (NOT the
# stdlib default opener, which auto-follows 30x and would silently bypass
# the redirect-target allowlist check below). Tests monkeypatch this name.
_opener = urllib.request.build_opener(_NoRedirect)
urlopen = _opener.open


def is_allowed(url: str, allowlist: list[str]) -> bool:
    """Return True if `url`'s host is on `allowlist` AND any 30x redirect
    target is also on the allowlist; False otherwise.

    Any exception raised during parsing or the HEAD probe is swallowed
    and surfaces as `False` — the call site treats "we couldn't verify"
    the same as "not allowed".
    """
    allowed: set[str] = set(allowlist)

    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.netloc not in allowed:
        return False

    try:
        req = urllib.request.Request(url, method="HEAD")
        # Module-local `urlopen` is bound to a no-follow-redirects opener
        # (built above), so a 30x response surfaces here as-is instead of
        # being auto-followed past the redirect-target allowlist check.
        # Tests monkeypatch `urlopen` directly.
        response = urlopen(req, timeout=_TIMEOUT_SECONDS)
    except HTTPError as e:
        # The no-follow opener surfaces 30x as HTTPError (its `redirect_request`
        # returns None, so the redirect handler falls through to the default
        # error path). HTTPError IS a response object — it exposes `.code` /
        # `.status` and `.getheader()` — so treat it as one and let the
        # Location-on-allowlist check below run. Without this branch the broad
        # `except Exception: return False` would reject *every* redirect,
        # including ones to allowlisted targets.
        response = e
    except Exception:
        return False

    # HTTPError exposes `.code`; `addinfourl` (normal urlopen response) exposes
    # `.status`. Accept either so both production paths flow into the
    # 30x-with-Location branch consistently.
    status = getattr(response, "status", None)
    if status is None:
        status = getattr(response, "code", None)
    if status in _REDIRECT_STATUSES:
        try:
            location = response.getheader("Location")
        except Exception:
            location = None
        if not location:
            return False
        try:
            target_netloc = urlparse(location).netloc
        except Exception:
            return False
        if not target_netloc:
            # Relative redirect (e.g., `Location: /next` or `Location: ../foo`)
            # stays on the original request's netloc — which `parsed.netloc`
            # already passed the allowlist check above. Without this branch,
            # `urlparse("/next").netloc == ""` would falsely reject every
            # legitimate same-host redirect.
            target_netloc = parsed.netloc
        return target_netloc in allowed

    # 200-level (or anything else non-30x with an on-allowlist netloc) → True.
    return True
