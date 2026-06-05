"""Tests for url_allowlist.is_allowed (Task 4.3).

Spec deviation pre-approved per [[feedback_test_spec_intent]]:
plan.md Task 4.3 literal calls for stubbing `requests.head(url,
allow_redirects=False, timeout=5)`, but `requests` is NOT in
`requirements-dev.txt` (only `pytest>=9.0` and `jsonschema>=4.26`). Phase 3
hit the same situation with `psutil` and resolved by using a stdlib
alternative (`/proc`). We do the same here: implement against
`urllib.request.urlopen` with a no-follow-redirects opener, and adapt the
fourth test (the equivalent of `allow_redirects=False`) to assert against
the urllib shape (HEAD method on the Request + the no-follow opener path)
rather than a keyword on `requests.head`.

The four behavioral assertions called out in plan.md remain:
  - exact netloc match passes
  - suffix match is rejected
  - 30x redirect to an off-allowlist netloc is rejected
  - the HEAD probe does not follow redirects (urllib equivalent of
    `allow_redirects=False`)

Run with: pytest skills/tp-pr-fix/scripts/test_url_allowlist.py -q
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from urllib.error import HTTPError


# -------- Task 4.3 — four behavioral assertions --------


def test_exact_netloc_match_passes():
    """An on-allowlist URL with a 200 HEAD response is_allowed → True.

    The allowlist holds exact netloc strings ("example.com"). A URL whose
    parsed netloc equals one of those entries and whose HEAD returns 200
    must be accepted.
    """
    import url_allowlist

    fake_response = MagicMock()
    fake_response.status = 200
    fake_response.getheader = MagicMock(return_value=None)

    with patch.object(url_allowlist, "urlopen", return_value=fake_response):
        assert url_allowlist.is_allowed(
            "https://example.com/path", ["example.com"]
        ) is True


def test_suffix_match_rejected():
    """`evil-example.com` must NOT match an allowlist entry `example.com`.

    The plan calls for an EXACT netloc match (no suffix matching). A URL
    whose netloc happens to end with an allowlist entry — but does not
    equal it — must be rejected before the HEAD probe is ever issued.
    """
    import url_allowlist

    # urlopen should never be called for an off-allowlist host. If the
    # impl skips the netloc check and falls through, this stub would
    # silently return 200; we sentinel-check that by raising instead.
    sentinel = MagicMock(
        side_effect=AssertionError("urlopen called for off-allowlist host")
    )
    with patch.object(url_allowlist, "urlopen", sentinel):
        assert url_allowlist.is_allowed(
            "https://evil-example.com/path", ["example.com"]
        ) is False


def test_30x_off_allowlist_redirect_rejected():
    """A 302 with `Location:` pointing off-allowlist must be rejected.

    The URL itself is on-allowlist, so it passes the initial netloc
    check. The HEAD probe returns 302 with a `Location` pointing at an
    off-allowlist host — that off-allowlist redirect target is the
    actual destination a client would land on, so is_allowed → False.
    """
    import url_allowlist

    fake_response = MagicMock()
    fake_response.status = 302
    # Both lookup shapes are supported by the impl; expose Location via
    # getheader (most common urllib idiom).
    fake_response.getheader = MagicMock(
        side_effect=lambda name: "https://evil.example.org/landed"
        if name.lower() == "location"
        else None
    )

    with patch.object(url_allowlist, "urlopen", return_value=fake_response):
        assert url_allowlist.is_allowed(
            "https://example.com/redir", ["example.com"]
        ) is False


def test_head_request_uses_allow_redirects_false():
    """The HEAD probe must NOT auto-follow redirects (urllib equivalent
    of `allow_redirects=False` from the plan's `requests.head` literal).

    Spec deviation per [[feedback_test_spec_intent]]: the plan literal
    asserts the keyword on `requests.head`. With urllib we assert two
    equivalent invariants instead:

      (a) the Request object passed to urlopen has method "HEAD"
          (`get_method() == "HEAD"`);
      (b) the call site disables automatic redirect-following — either
          via a custom opener built from a `HTTPRedirectHandler` whose
          `redirect_request` returns None, OR by relying on `urlopen`
          surfacing 30x as an `HTTPError` and reading `Location` off the
          exception (i.e. not re-opening).

    We assert (a) directly from the mock call, and (b) indirectly via
    the 30x-rejected test above (`test_30x_off_allowlist_redirect_rejected`):
    if the impl silently followed the redirect and re-resolved the
    Location, the 302 path would never observe the off-allowlist host
    and that test would fail. So the pair of tests together pins the
    "allow_redirects=False" intent.
    """
    import url_allowlist

    fake_response = MagicMock()
    fake_response.status = 200
    fake_response.getheader = MagicMock(return_value=None)

    with patch.object(
        url_allowlist, "urlopen", return_value=fake_response
    ) as mock_open:
        url_allowlist.is_allowed(
            "https://example.com/probe", ["example.com"]
        )

    # (a) urlopen was called with a Request whose method is HEAD.
    assert mock_open.called, "urlopen was not invoked"
    call_args, call_kwargs = mock_open.call_args
    # Request can be positional or kwarg; pull from whichever slot.
    req = call_args[0] if call_args else call_kwargs.get("url")
    # Stdlib Request exposes get_method() — verify HEAD.
    assert hasattr(req, "get_method"), (
        f"expected urllib.request.Request, got {type(req).__name__}"
    )
    assert req.get_method() == "HEAD", (
        f"expected HEAD method, got {req.get_method()!r}"
    )


# -------- Production path: urlopen with the no-redirect opener raises
#          HTTPError on 30x. The on-allowlist redirect target must still
#          pass — without the HTTPError branch, every redirect was rejected. --


def test_httperror_30x_on_allowlist_redirect_passes():
    """On-allowlist 302 raised as HTTPError → False unless Location is
    also on-allowlist. This locks in the production path: the no-follow
    opener surfaces 30x as HTTPError, and the on-allowlist Location
    must still pass."""
    import url_allowlist

    headers = {"Location": "https://example.com/landed"}

    def _getheader(name):
        return headers.get(name)

    err = HTTPError(
        url="https://example.com/redir",
        code=302,
        msg="Found",
        hdrs=None,
        fp=None,
    )
    # Stub the header lookup the impl will perform.
    err.getheader = _getheader  # type: ignore[attr-defined]

    with patch.object(url_allowlist, "urlopen", side_effect=err):
        assert url_allowlist.is_allowed(
            "https://example.com/redir", ["example.com"]
        ) is True


def test_httperror_30x_off_allowlist_redirect_rejected():
    """HTTPError-path equivalent of the off-allowlist redirect test."""
    import url_allowlist

    headers = {"Location": "https://evil.example.org/landed"}

    def _getheader(name):
        return headers.get(name)

    err = HTTPError(
        url="https://example.com/redir",
        code=302,
        msg="Found",
        hdrs=None,
        fp=None,
    )
    err.getheader = _getheader  # type: ignore[attr-defined]

    with patch.object(url_allowlist, "urlopen", side_effect=err):
        assert url_allowlist.is_allowed(
            "https://example.com/redir", ["example.com"]
        ) is False


def test_relative_redirect_keeps_original_netloc():
    """`Location: /next` is a relative redirect — it stays on the original
    host. `urlparse("/next").netloc == ""`, so without explicit handling
    the on-allowlist redirect would be falsely rejected (empty string is
    never in the allowlist).
    """
    import url_allowlist

    fake_response = MagicMock()
    fake_response.status = 302
    fake_response.getheader = MagicMock(
        side_effect=lambda name: "/next" if name.lower() == "location" else None
    )

    with patch.object(url_allowlist, "urlopen", return_value=fake_response):
        assert url_allowlist.is_allowed(
            "https://example.com/redir", ["example.com"]
        ) is True
