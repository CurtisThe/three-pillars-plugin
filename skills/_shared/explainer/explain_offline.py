"""explainer/explain_offline.py — the core offline-first assertion.

Public API:
  assert_offline(html)    raises AssertionError on any external resource ref

The explainer's output is a single self-contained HTML file: no network fetch,
no CDN, no web font. ``assert_offline`` is the one check every renderer runs on
what it emits. ``_strip_namespaces`` is its pre-pass (W3C ``xmlns`` declarations
and base64 ``data:`` payloads are inline/structural, not network refs) and is
re-exported for callers that mirror the same pre-pass.

Stdlib only. Flat-import package — no __init__.py.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ---------------------------------------------------------------------------
# Patterns for assert_offline
# ---------------------------------------------------------------------------
# Strategy: strip known-safe namespace URIs first, then scan.
# SVG xmlns="http://www.w3.org/2000/svg" and similar W3C namespace declarations
# are structural markup, not network requests.  We strip them before pattern
# matching rather than trying to exclude them inside each regex.

_NAMESPACE_STRIP_RE = re.compile(
    r'xmlns(?::[a-z]+)?\s*=\s*"https?://(?:www\.)?w3\.org/[^"]*"',
    re.IGNORECASE,
)

# A base64 data: payload routinely contains "//" (the base64 alphabet includes
# "/"), which would otherwise false-positive the protocol-relative pattern below
# on a perfectly offline inline image. Strip ONLY the base64 run, keeping the
# `data:<mediatype>;base64,` prefix so the src/href exemption still recognizes
# it. Scoped to base64 deliberately: a NON-base64 `data:text/html,<…>` URI can
# render inline markup that *does* fetch externally, so its content must stay
# scannable — we do not blanket-strip every data: URI.
_DATA_URI_B64_STRIP_RE = re.compile(
    r'(data:[^,"\'\s)]*;base64,)[A-Za-z0-9+/=]+', re.IGNORECASE)


def _strip_namespaces(html: str) -> str:
    """Remove XML/SVG namespace declarations + neutralize base64 data: payloads
    before offline-scanning (both are inline/structural, not network refs)."""
    stripped = _NAMESPACE_STRIP_RE.sub('xmlns="STRIPPED"', html)
    return _DATA_URI_B64_STRIP_RE.sub(r'\1STRIPPED', stripped)


# Patterns that indicate an external resource reference (case-insensitive).
# Applied AFTER namespace declarations are stripped.
_EXTERNAL_PATTERNS = [
    re.compile(r"https?:", re.IGNORECASE),               # http: / https:
    re.compile(r"(?<!['\"/])//[^/>]", re.IGNORECASE),   # protocol-relative //host
    re.compile(r"@import", re.IGNORECASE),
    # url( not followed by data: or # or )
    re.compile(r"url\(\s*(?![\"']?(?:data:|#|\)))", re.IGNORECASE),
    re.compile(r"\bfetch\s*\(", re.IGNORECASE),
    re.compile(r"\bXMLHttpRequest\b", re.IGNORECASE),
]

# src= or href= pointing to an external URL (not # or data:)
_SRC_HREF_RE = re.compile(
    r"""(?:src|href)\s*=\s*["'](?!(?:#|data:))""",
    re.IGNORECASE,
)


def assert_offline(html: str) -> None:
    """Assert the HTML/SVG document contains no external resource references.

    Raises AssertionError with a descriptive message on the first violation.
    Safe to call on both full documents and fragments.

    Checks (case-insensitive):
    - http: / https: URLs
    - protocol-relative // URLs (//cdn.example.com/…)
    - @import directives
    - url() with non-data:/non-# targets
    - fetch() / XMLHttpRequest
    - src= or href= not starting with # or data:

    XML/SVG namespace declarations (xmlns="http://…") are structural and
    are excluded from the scan before pattern matching.
    """
    # Strip namespace declarations before scanning so SVG xmlns="http://…"
    # is not flagged as an external resource.
    scanned = _strip_namespaces(html)

    for pattern in _EXTERNAL_PATTERNS:
        m = pattern.search(scanned)
        if m:
            context = scanned[max(0, m.start() - 20): m.end() + 20]
            raise AssertionError(
                f"External resource detected: pattern={pattern.pattern!r} "
                f"near: ...{context!r}..."
            )
    m = _SRC_HREF_RE.search(scanned)
    if m:
        context = scanned[max(0, m.start() - 10): m.end() + 30]
        raise AssertionError(
            f"External src/href detected near: ...{context!r}..."
        )
