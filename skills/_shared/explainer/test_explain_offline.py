"""Tests for explainer/explain_offline.py — the core offline-first assertion.

Covers explainer-agent plan Task 1.1: ``assert_offline`` lives in the core
explainer package. It raises ``AssertionError`` on a document that would fetch
an external resource and returns ``None`` on a self-contained one, including an
inline SVG whose W3C ``xmlns`` declaration is structural, not a network ref.
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest  # noqa: E402

import explain_offline  # noqa: E402


@pytest.mark.parametrize(
    "html",
    [
        '<script src="https://cdn.example/x.js"></script>',
        '<img src="//host/x.png">',
        "<style>@import url(x)</style>",
    ],
    ids=["https-script", "protocol-relative-img", "css-import"],
)
def test_external_reference_raises(html):
    with pytest.raises(AssertionError):
        explain_offline.assert_offline(html)


@pytest.mark.parametrize(
    "html",
    [
        "<p>offline</p>",
        '<svg xmlns="http://www.w3.org/2000/svg"><rect width="4" height="4"/></svg>',
    ],
    ids=["plain-paragraph", "inline-svg-namespace"],
)
def test_self_contained_document_returns_none(html):
    assert explain_offline.assert_offline(html) is None
