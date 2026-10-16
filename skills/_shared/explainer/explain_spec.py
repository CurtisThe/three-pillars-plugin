"""explainer/explain_spec.py — diagram_spec sanitization + validation.

Public API:
    ALLOWED_KINDS   tuple of valid kind strings
    MAX_NODES       maximum node count cap
    MAX_EDGES       maximum edge count cap
    sanitize_spec(spec) -> Optional[dict]
    _strip_external(text: str) -> str

sanitize_spec is the security trust gate for LLM-proposed diagram specs.
It validates the fixed grammar (kind ∈ ALLOWED_KINDS), reads node and edge
items through explain_spec_shape ({id, label} node dicts; [src, dst],
{from, to} or {source, target} edges), coerces and sanitizes all labels,
caps node/edge counts, and drops dangling edges. Returns None when the spec
is unusable — the renderer will simply omit the diagram: a container where
an id, endpoint or label belongs (never str()-ed), or a degenerate spec
(every given edge dropped, or a flow / state with 2+ nodes and no edge). A
raw diagram (a string, or a dict carrying an svg / mermaid / html key) is
always None. The before-after and sequence kinds are sanitized by
explain_spec_ext.

_strip_external removes/neutralizes any substring that assert_offline
would flag:  http(s):, protocol-relative //host, url(, @import,
<svg/<image/xlink/<script, and every data: URI EXCEPT base64
image/audio/video (the _DATA_ALLOW_RE allowlist, Finding 6).

Stdlib only. Flat-import package — no __init__.py.
"""
from __future__ import annotations

import html as _html
import re
import sys
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import explain_spec_ext as _ext  # noqa: E402
import explain_spec_shape as _shape  # noqa: E402

# ---------------------------------------------------------------------------
# Grammar constants
# ---------------------------------------------------------------------------

ALLOWED_KINDS = ("flow", "decision", "state") + _ext.KINDS

# A spec carrying any of these keys is raw markup, never a spec.
_RAW_DIAGRAM_KEYS = ("svg", "mermaid", "html")

# Safety caps — keep rendered SVGs tractable.
MAX_NODES = 20
MAX_EDGES = 40

# ---------------------------------------------------------------------------
# data: allowlist (Finding 6)
# Only base64 image/audio/video data: URIs are permitted.
# All other data: URIs (text/*, application/*, non-base64) are stripped.
# ---------------------------------------------------------------------------

_DATA_ALLOW_RE = re.compile(
    r"^data:(image|audio|video)/[a-z0-9.+\-]+;base64,[A-Za-z0-9+/=]+$",
    re.IGNORECASE,
)

# Patterns to strip — ordered from most-specific to least-specific.
# We replace matched substrings with an empty string (or a safe token).

# Strips full data: URIs that do NOT match the allowlist.
# Matches 'data:' followed by non-whitespace, non-quote, non-paren chars.
_DATA_URI_RE = re.compile(
    r"data:[^\s\"'<>()]+",
    re.IGNORECASE,
)

# http(s): scheme
_HTTP_RE = re.compile(r"https?:", re.IGNORECASE)

# protocol-relative: // preceded by a char that is NOT ' " / (i.e. not already
# in a safe context).  We strip the // itself to defuse the pattern.
# Use a broader match to be safe in spec/label context: strip any '//'
_PROTO_REL_RE = re.compile(r"//")

# url( function — strip the whole url(...) call or just the keyword
_URL_FUNC_RE = re.compile(r"url\s*\(", re.IGNORECASE)

# @import directive
_IMPORT_RE = re.compile(r"@import", re.IGNORECASE)

# Dangerous inline tags and attributes
_TAG_RE = re.compile(
    r"<(?:svg|image|script|iframe|object|embed|link|style)[^>]*>",
    re.IGNORECASE,
)
_XLINK_RE = re.compile(r"xlink", re.IGNORECASE)

# href= or src= attribute — strip the whole attribute to avoid naked href='...'
# passing assert_offline's _SRC_HREF_RE check.
_HREF_ATTR_RE = re.compile(r"""(?:href|src)\s*=\s*["'][^"']*["']""", re.IGNORECASE)

# assert_offline also checks for fetch( and XMLHttpRequest — strip them from labels.
_FETCH_RE = re.compile(r"\bfetch\s*\(", re.IGNORECASE)
_XHR_RE = re.compile(r"\bXMLHttpRequest\b", re.IGNORECASE)


def _strip_external(text: str) -> str:
    """Remove/neutralize any substring that assert_offline would flag.

    Strips (in order per iteration):
      1. data: URIs that don't match _DATA_ALLOW_RE  (Finding 6)
      2. http(s): scheme
      3. // (protocol-relative host prefix, also neutralizes bare //)
      4. url( CSS function
      5. @import directive
      6. dangerous inline tags (<svg>, <script>, <image>, xlink)
      7. fetch( and XMLHttpRequest

    Runs to a FIXED POINT (Finding 2): the full substitution set is applied
    repeatedly until the output stops changing.  This prevents adversarial
    interleaved inputs (e.g. 'htHTTP:tp:/X/') from reconstituting a
    forbidden scheme after a single pass.

    Iteration is bounded to _MAX_STRIP_ROUNDS to guard against pathological
    inputs; on cap the result has had all identifiable patterns stripped many
    times over and is safe in practice.

    The result is safe for inline HTML embedding and will pass
    briefing.assert_offline when wrapped in a minimal HTML context.
    """
    _MAX_STRIP_ROUNDS = 20

    def _apply_once(s: str) -> str:
        # 1. Handle data: URIs — keep allowlisted, strip everything else.
        def _filter_data_uri(m: re.Match) -> str:
            uri = m.group(0)
            if _DATA_ALLOW_RE.match(uri):
                return uri  # allowed — keep as-is
            return ""       # strip disallowed data: URI

        s = _DATA_URI_RE.sub(_filter_data_uri, s)
        # 2. Strip http(s): scheme
        s = _HTTP_RE.sub("", s)
        # 3. Strip // (protocol-relative and bare double-slash)
        s = _PROTO_REL_RE.sub("", s)
        # 4. Strip url( function
        s = _URL_FUNC_RE.sub("", s)
        # 5. Strip @import
        s = _IMPORT_RE.sub("", s)
        # 6. Strip dangerous tags, xlink, and bare href=/src= attributes
        s = _TAG_RE.sub("", s)
        s = _XLINK_RE.sub("", s)
        s = _HREF_ATTR_RE.sub("", s)
        # 7. Strip fetch( and XMLHttpRequest (assert_offline patterns)
        s = _FETCH_RE.sub("", s)
        s = _XHR_RE.sub("", s)
        return s

    result = str(text)
    for _ in range(_MAX_STRIP_ROUNDS):
        next_result = _apply_once(result)
        if next_result == result:
            break
        result = next_result
    return result


# ---------------------------------------------------------------------------
# Unconditional token neutralizers (single-pass, guaranteed-terminating)
# ---------------------------------------------------------------------------
# These run AFTER _strip_external's iterative removal and neutralize whatever
# assert_offline-triggering tokens survive the capped strip loop.
#
# Strategy (escape-stable): break each triggering pattern by REMOVING the
# punctuation that makes it match — never by emitting an HTML entity. The old
# entity strategy (e.g. "https:" → "https&#58;") was NOT escape-stable: the
# label is html.escaped exactly once at draw time in explain_svg._esc, which
# re-encodes the entity's "&" → "&amp;", producing "https&amp;#58;". That
# double-encoded artifact renders as the literal text "https&#58;" (HTML
# character-reference parsing is single-pass, so the colon is NOT restored to
# an active ":"), violating the "display-identical" contract and leaving
# confusing garbage on screen. Removing the triggering character introduces no
# "&", so the once-at-draw html.escape is a no-op on these substitutions and
# the output is stable under escaping. This mirrors _strip_external's own
# removal strategy, so both stages neutralize the same way.

# http: / https: → drop the colon ("https:" → "https")
_NEUTRALIZE_HTTP_RE = re.compile(r"https?:", re.IGNORECASE)
# // → remove (also defuses any "//" created by dropping a scheme colon)
_NEUTRALIZE_PROTO_REL_RE = re.compile(r"//")
# url( → drop the paren ("url(" → "url")
_NEUTRALIZE_URL_RE = re.compile(r"url(\s*)\(", re.IGNORECASE)
# @import → drop the @ ("@import" → "import")
_NEUTRALIZE_IMPORT_RE = re.compile(r"@import", re.IGNORECASE)
# fetch( → drop the paren ("fetch(" → "fetch")
_NEUTRALIZE_FETCH_RE = re.compile(r"\bfetch(\s*)\(", re.IGNORECASE)
# XMLHttpRequest → break the word with a hyphen ("XMLHttp-Request")
_NEUTRALIZE_XHR_RE = re.compile(r"\bXMLHttpRequest\b")


def _neutralize_tokens(text: str) -> str:
    """Unconditionally neutralize assert_offline tokens, escape-stable.

    Applied after _strip_external so any scheme/token reconstituted at the
    strip-loop cap boundary cannot survive into the SVG text node. Each
    substitution removes the triggering punctuation rather than emitting an
    HTML entity, so the output contains no "&" and is INVARIANT under the
    once-at-draw html.escape in explain_svg._esc (no double-encoding).

    Removal can expose a fresh token (dropping a scheme colon leaves the
    trailing "//"; collapsing "uurl((" yields "uurl("), so the substitution
    set runs to a FIXED POINT, capped at _MAX_NEUTRALIZE_ROUNDS. On cap the
    output has had every identifiable pattern removed many times over and is
    safe in practice (mirrors _strip_external's bounded fixed-point loop).
    """
    _MAX_NEUTRALIZE_ROUNDS = 20

    def _apply_once(s: str) -> str:
        # http:/https: → drop the colon (before "//" so an exposed "//" clears)
        s = _NEUTRALIZE_HTTP_RE.sub(lambda m: m.group(0)[:-1], s)
        # // → remove
        s = _NEUTRALIZE_PROTO_REL_RE.sub("", s)
        # url( → url
        s = _NEUTRALIZE_URL_RE.sub(lambda m: "url" + m.group(1), s)
        # @import → import
        s = _NEUTRALIZE_IMPORT_RE.sub("import", s)
        # fetch( → fetch
        s = _NEUTRALIZE_FETCH_RE.sub(lambda m: "fetch" + m.group(1), s)
        # XMLHttpRequest → XMLHttp-Request (hyphen breaks the \bword\b match)
        s = _NEUTRALIZE_XHR_RE.sub("XMLHttp-Request", s)
        return s

    result = str(text)
    for _ in range(_MAX_NEUTRALIZE_ROUNDS):
        next_result = _apply_once(result)
        if next_result == result:
            break
        result = next_result
    return result


def _sanitize_label(value) -> str:
    """Coerce to str, strip external refs, then neutralize surviving tokens.

    Two-stage defense:
      1. _strip_external: iterative removal of hostile patterns (tags, schemes,
         xlink, href/src, data: URIs) to a fixed point, capped at 20 rounds.
      2. _neutralize_tokens: unconditional single-pass neutralization of any
         assert_offline token that survived the cap (e.g. reconstituted http:
         from pathological interleaved input like 'h'*25+'ttp:'*25).

    DOES NOT html.escape — that happens exactly once at draw time in
    explain_svg._esc().  Keeping the raw text here prevents double-escape when
    sanitize_spec is called at narrate time AND again inside spec_svg.
    """
    stripped = _strip_external(str(value))
    return _neutralize_tokens(stripped)


def sanitize_spec(spec) -> Optional[dict]:
    """Validate and sanitize a diagram_spec dict.

    Returns a normalized {kind, nodes, edges, labels} dict with:
      - kind ∈ ALLOWED_KINDS (else returns None)
      - labels coerced to str and run through _strip_external (no html.escape
        here — escaping happens exactly once at draw time in explain_svg._esc)
      - node/edge counts capped at MAX_NODES / MAX_EDGES
      - node ids coerced to str; a {id, label} node dict gives its id, and
        its label joins labels unless the spec's labels already name the node
      - edges as [src, dst]; {from, to} / {source, target} dicts accepted
      - edges referencing unknown nodes dropped

    Returns None when the spec is unusable so the renderer omits the diagram:
    a raw diagram (a non-dict, or a dict with a _RAW_DIAGRAM_KEYS key); a
    container (or non-string node-dict id) where an id, endpoint or label
    belongs (explain_spec_shape.ShapeError); or a degenerate spec per
    explain_spec_shape.is_degenerate. A decision with no edges is kept.
    The explain_spec_ext kinds return explain_spec_ext.sanitize_ext's shape.
    """
    if not isinstance(spec, dict):
        return None
    if not spec or any(k in spec for k in _RAW_DIAGRAM_KEYS):
        return None

    # Validate kind
    kind = spec.get("kind")
    if kind not in ALLOWED_KINDS:
        return None
    if kind in _ext.KINDS:
        return _ext.sanitize_ext(spec, sanitize_label=_sanitize_label)

    raw_nodes = spec.get("nodes")
    if not isinstance(raw_nodes, list):
        return None
    try:
        nodes, node_labels = _shape.sanitize_nodes(raw_nodes[:MAX_NODES],
                                                   _sanitize_label)
        edges, given = _shape.sanitize_links(spec.get("edges"), set(nodes),
                                             _sanitize_label, MAX_EDGES)
        labels = _shape.sanitize_labels(spec.get("labels"), node_labels,
                                        _sanitize_label)
    except _shape.ShapeError:
        return None
    if _shape.is_degenerate(kind, nodes, given, edges):
        return None

    return {
        "kind": kind,
        "nodes": nodes,
        "edges": edges,
        "labels": labels,
    }
