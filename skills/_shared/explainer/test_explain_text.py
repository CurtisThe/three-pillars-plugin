"""test_explain_text.py — tests for explain_text.safe_text.

Behavior 6 / Finding 3:
  - html.escape does NOT touch '//'; safe_text must neutralize it.
  - After safe_text, assert_offline must not raise on the result.
  - HTML special chars (<, >, ", &) are escaped.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import pytest

import explain_offline as briefing


# ---------------------------------------------------------------------------
# Task 3.1: safe_text — esc THEN //-neutralize
# ---------------------------------------------------------------------------

def test_safe_text_neutralizes_double_slash():
    """// in model prose must become &#47;&#47; so assert_offline won't fire."""
    from explain_text import safe_text
    result = safe_text("see //example")
    assert "&#47;&#47;" in result
    assert "//" not in result


def test_safe_text_html_escape():
    """HTML special chars must be escaped."""
    from explain_text import safe_text
    result = safe_text('<script>alert("xss")</script>&')
    assert "&lt;script&gt;" in result
    assert "&amp;" in result
    assert "&quot;" in result


def test_safe_text_assert_offline_does_not_raise():
    """safe_text output must pass briefing.assert_offline (Finding 3).

    html.escape does NOT touch '//', so without safe_text's // replacement,
    'see //example' would fire the protocol-relative pattern.
    """
    from explain_text import safe_text
    result = safe_text("see //example")
    # This is the core of Finding 3 — must not raise
    briefing.assert_offline(result)


def test_safe_text_assert_offline_on_http_in_plain_text():
    """'http:' in plain text (not in an href) should not leak through safe_text."""
    from explain_text import safe_text
    # html.escape leaves 'http:' intact, so safe_text must also strip it
    # or ensure assert_offline won't fire. The spec says _esc THEN //-neutralize.
    # The 'http:' pattern IS caught by assert_offline but safe_text's job is only
    # //-neutralize per the design (the caller should not put raw URLs in narrative).
    # This test documents the behavior: http: after safe_text is still http:
    # (safe_text is not a URL-stripper, that's sanitize_spec's job).
    result = safe_text("visit http://example.com")
    # http: passes through safe_text — that's expected; the sanitizer handles URLs.
    # But the // after http: gets neutralized to &#47;&#47;
    # Result: "visit http:&#47;&#47;example.com" — which passes assert_offline
    # because the https?: pattern needs "http:" followed by "//" to be a URL.
    # Actually let's verify: assert_offline checks for "https?:" which matches "http:"
    # So safe_text('http://example.com') should still make assert_offline happy.
    # The // is neutralized but "http:" remains — check if assert_offline fires on bare "http:"
    # The pattern is r"https?:" so it matches bare "http:" too.
    # So for raw http URLs, assert_offline would still fire. The narrative should
    # not contain raw http: URLs. safe_text neutralizes // but not http:.
    # That is intentional — narrate is expected to not include raw URLs.
    # Document that // is neutralized:
    assert "&#47;&#47;" in result or "//" not in result


def test_safe_text_plain_text_unchanged():
    """Plain text with no special chars passes through unchanged."""
    from explain_text import safe_text
    result = safe_text("normal text here")
    assert result == "normal text here"


def test_safe_text_empty_string():
    """Empty string returns empty string."""
    from explain_text import safe_text
    assert safe_text("") == ""


def test_safe_text_multiple_double_slashes():
    """All occurrences of // are neutralized."""
    from explain_text import safe_text
    result = safe_text("see //foo and //bar")
    assert "//" not in result
    assert result.count("&#47;&#47;") == 2


def test_safe_text_protocol_relative_passes_assert_offline():
    """A string like '//cdn.example' through safe_text passes assert_offline."""
    from explain_text import safe_text
    hostile = "reference //cdn.example/resource"
    result = safe_text(hostile)
    # Must not raise
    briefing.assert_offline(result)


def test_safe_text_ampersand_escaped():
    """& is escaped to &amp;."""
    from explain_text import safe_text
    result = safe_text("rock & roll")
    assert "&amp;" in result
    assert "& " not in result


def test_safe_text_quote_escaped():
    """Double quotes are escaped to &quot; (quote=True)."""
    from explain_text import safe_text
    result = safe_text('He said "hello"')
    assert "&quot;" in result


def test_safe_text_single_slash_unchanged():
    """A single / is not affected."""
    from explain_text import safe_text
    result = safe_text("path/to/file")
    assert result == "path/to/file"


# ---------------------------------------------------------------------------
# Finding 1 (B7/B8): safe_text must also neutralize the http(s): scheme
# These tests FAIL on the unpatched code — they prove the bypass is real.
# ---------------------------------------------------------------------------

def test_safe_text_https_scheme_neutralized():
    """https: scheme must be neutralized so assert_offline does not raise."""
    from explain_text import safe_text
    result = safe_text("https://ci.example")
    # The bare https: pattern must be gone from the output
    import re
    assert not re.search(r"https?:", result, re.IGNORECASE), (
        f"https: scheme survived safe_text: {result!r}"
    )


def test_safe_text_http_scheme_neutralized():
    """http: scheme must be neutralized so assert_offline does not raise."""
    from explain_text import safe_text
    result = safe_text("see http://evil.example")
    import re
    assert not re.search(r"https?:", result, re.IGNORECASE), (
        f"http: scheme survived safe_text: {result!r}"
    )


def test_safe_text_mixed_case_https_neutralized():
    """Mixed-case HtTpS: must be neutralized by safe_text."""
    from explain_text import safe_text
    result = safe_text("HtTpS://evil.example")
    import re
    assert not re.search(r"https?:", result, re.IGNORECASE), (
        f"Mixed-case scheme survived safe_text: {result!r}"
    )


def test_safe_text_https_in_narrative_passes_assert_offline():
    """Narrative with https:// URL must pass assert_offline after safe_text."""
    from explain_text import safe_text
    result = safe_text("see https://ci.example for details")
    briefing.assert_offline(result)


def test_safe_text_http_in_decision_focus_passes_assert_offline():
    """decision_focus value with http:// must pass assert_offline after safe_text."""
    from explain_text import safe_text
    result = safe_text("check: http://ci.example/status")
    briefing.assert_offline(result)


# The full-document checks (rendered through live_render.build_live_html) live
# in html_briefing/test_explainer_path_shim.py: live_render is html_briefing's,
# and the core explainer package never imports html_briefing.


# ---------------------------------------------------------------------------
# Hermetic battery: safe_text must neutralize EVERY assert_offline pattern.
# These tests FAIL on the partially-fixed safe_text (url(, @import, fetch(,
# XMLHttpRequest still pass through) and PASS after the comprehensive fix.
# ---------------------------------------------------------------------------

# Every hostile token that assert_offline's _EXTERNAL_PATTERNS or
# _SRC_HREF_RE could match in free text:
_HOSTILE_STRINGS = [
    "https://x.test",
    "http://x.test",
    "HtTpS://x.test",
    "//x.test",
    "url(//d.test)",
    "url(http://x.test)",
    "@import url(evil.css)",
    "fetch(http://x.test)",
    "new XMLHttpRequest()",
]


def test_safe_text_hermetic_battery_each_string():
    """safe_text output for every hostile string must pass assert_offline."""
    from explain_text import safe_text
    failures = []
    for hostile in _HOSTILE_STRINGS:
        result = safe_text(hostile)
        try:
            briefing.assert_offline(result)
        except AssertionError as e:
            failures.append(f"safe_text({hostile!r}) -> {result!r}: {e}")
    assert not failures, "safe_text still leaks patterns:\n" + "\n".join(failures)
