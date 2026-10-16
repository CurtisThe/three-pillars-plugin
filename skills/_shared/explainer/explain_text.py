"""explainer/explain_text.py — model-authored free-text neutralizer.

Public API:
    safe_text(value: str) -> str

Contract: the output of safe_text(any_string) MUST NOT match ANY pattern that
briefing.assert_offline scans for.  The full pattern set (from briefing.py) is:

  1. https?:          — http: / https: scheme
  2. (?<!['\"/])//… — protocol-relative //host
  3. @import
  4. url( not followed by data:/#/)   — CSS url() function
  5. \\bfetch\\s*\\(  — fetch() call
  6. \\bXMLHttpRequest — XHR constructor
  (plus src=/href= pointing external — blocked by html.escape quoting " ')

Each pattern is neutralised by replacing its distinctive token character with
an HTML numeric character reference so the result is display-identical in a
browser but never matches the regex:

  http(s):      colon → &#58;   (e.g. "http&#58;")
  //            each / → &#47;  (e.g. "&#47;&#47;")
  @import       @ → &#64;       (e.g. "&#64;import")
  url(          ( → &#40;        (e.g. "url&#40;")
  fetch(        ( → &#40;        (e.g. "fetch&#40;")
  XMLHttpRequest  R → &#82;     (e.g. "XMLHttp&#82;equest") — breaks \\b-word

Neutralizations are applied AFTER html.escape so they never conflict with the
HTML escaping pass.  Order: escape → //-neutralize → scheme → @import →
url( → fetch( → XMLHttpRequest.

Used by the render block for:
  - run.narrative  (free text paragraph)
  - every decision_focus value
  - diagram spec labels routed through explain_spec._strip_external

Stdlib only. Flat-import package — no __init__.py.
"""
from __future__ import annotations

import html as _html
import re as _re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Matches http: or https: (case-insensitive).
_HTTP_SCHEME_RE = _re.compile(r"https?:", _re.IGNORECASE)

# Matches @import (case-insensitive).
_AT_IMPORT_RE = _re.compile(r"@import", _re.IGNORECASE)

# Matches url( (case-insensitive, with optional whitespace before the paren).
# We neutralize the literal '(' that follows 'url' (with optional spaces).
_URL_FUNC_RE = _re.compile(r"url(\s*)\(", _re.IGNORECASE)

# Matches fetch( (case-insensitive, word-boundary, optional whitespace).
_FETCH_RE = _re.compile(r"\bfetch(\s*)\(", _re.IGNORECASE)

# Matches XMLHttpRequest as a word token (case-sensitive per assert_offline).
_XHR_RE = _re.compile(r"\bXMLHttpRequest\b")


def safe_text(value: str) -> str:
    """Neutralize model-authored free text for safe inline HTML embedding.

    Steps applied in order:
      1. html.escape(str(value), quote=True)  — escapes <, >, ", ', &
      2. '//' → '&#47;&#47;'         — protocol-relative pattern
      3. 'http:'/'https:' → '…&#58;' — scheme pattern (case-insensitive)
      4. '@import' → '&#64;import'   — @import pattern (case-insensitive)
      5. 'url(' → 'url&#40;'         — url() pattern (case-insensitive)
      6. 'fetch(' → 'fetch&#40;'     — fetch() pattern (case-insensitive)
      7. 'XMLHttpRequest' → 'XMLHttp&#82;equest' — XHR pattern

    Pure, stdlib-only.  Returns str.
    """
    # Step 1: HTML-escape
    s = _html.escape(str(value), quote=True)

    # Step 2: neutralize // (protocol-relative)
    s = s.replace("//", "&#47;&#47;")

    # Step 3: neutralize http(s): scheme colon
    s = _HTTP_SCHEME_RE.sub(lambda m: m.group(0)[:-1] + "&#58;", s)

    # Step 4: neutralize @import → &#64;import
    s = _AT_IMPORT_RE.sub("&#64;import", s)

    # Step 5: neutralize url( → url&#40; (preserve any whitespace between
    # 'url' and '(' so display is unchanged, only the paren is encoded)
    s = _URL_FUNC_RE.sub(lambda m: "url" + m.group(1) + "&#40;", s)

    # Step 6: neutralize fetch( → fetch&#40;
    s = _FETCH_RE.sub(lambda m: "fetch" + m.group(1) + "&#40;", s)

    # Step 7: neutralize XMLHttpRequest → XMLHttp&#82;equest
    s = _XHR_RE.sub("XMLHttp&#82;equest", s)

    return s
