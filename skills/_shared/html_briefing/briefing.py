"""html_briefing/briefing.py — public entry: build_briefing_html + assert_offline.

Public API:
  build_briefing_html(model) -> str   full self-contained HTML document
  assert_offline(html)                raises AssertionError on external refs

Stdlib only. Flat-import package — no __init__.py.
"""
from __future__ import annotations

import json
import re

# Inline assets (CSS + JS) are in assets.py to keep this file under the cap.
import assets
import renderer as _renderer
import serializer as _serializer
import svg as _svg


# ---------------------------------------------------------------------------
# assert_offline — shared offline-first assertion helper
# ---------------------------------------------------------------------------

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


def _strip_namespaces(html: str) -> str:
    """Remove XML/SVG namespace declarations before offline-scanning."""
    return _NAMESPACE_STRIP_RE.sub('xmlns="STRIPPED"', html)


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


# ---------------------------------------------------------------------------
# build_briefing_html
# ---------------------------------------------------------------------------

def build_briefing_html(model) -> str:
    """Build a self-contained offline HTML briefing document.

    Args:
        model: a BriefingModel with .seeds (list[SeedCard]) and
               .questions (ConfirmModel).

    Returns:
        A complete <!DOCTYPE html> document string with inline CSS/JS,
        embedded SVG visuals, and form controls.
    """
    cards_html = _renderer.render_cards(model.seeds)
    questions_html = _renderer.render_questions(model.questions)

    wave_svg = _svg.wave_topology_svg(model.wave_model)
    collision_svg = _svg.collision_matrix_svg(model.wave_model)
    progress_svg = _svg.progress_bar_svg(model.wave_model)

    # Build the question→letter map for embedded JS
    q_letter_map = _build_q_letter_map(model.questions)
    q_letter_map_json = json.dumps(q_letter_map)

    # Golden default string for round-trip assertion
    default_model = _make_default_model(model.questions)
    golden_defaults = _serializer.serialize_answers(default_model)

    css = assets.CSS
    js = assets.JS

    return _render_document(
        cards_html=cards_html,
        questions_html=questions_html,
        wave_svg=wave_svg,
        collision_svg=collision_svg,
        progress_svg=progress_svg,
        css=css,
        js=js,
        q_letter_map_json=q_letter_map_json,
        golden_defaults=golden_defaults,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_q_letter_map(confirm_model) -> dict:
    """Build {str(number): [letters]} from a ConfirmModel."""
    result = {}
    for q in confirm_model.questions:
        if q.kind != "free":
            result[str(q.number)] = [opt[0] for opt in q.options]
        else:
            result[str(q.number)] = []
    return result


def _make_default_model(confirm_model):
    """Return a copy of the ConfirmModel with chosen == default for every Q."""
    import copy
    qs = []
    for q in confirm_model.questions:
        q2 = copy.copy(q)
        if q.kind == "multi":
            q2.chosen = list(q.default)
        else:
            q2.chosen = q.default
        qs.append(q2)
    return _serializer.ConfirmModel(questions=qs)


def _render_document(
    *,
    cards_html: str,
    questions_html: str,
    wave_svg: str,
    collision_svg: str,
    progress_svg: str,
    css: str,
    js: str,
    q_letter_map_json: str,
    golden_defaults: str,
) -> str:
    import html as _html
    golden_attr = _html.escape(golden_defaults, quote=True)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Promote Briefing</title>
<style>
{css}
</style>
</head>
<body>
<div id="briefing">
  <section id="seeds">
{cards_html}
  </section>
  <section id="visuals">
    <div class="svg-block">{wave_svg}</div>
    <div class="svg-block">{collision_svg}</div>
    <div class="svg-block">{progress_svg}</div>
  </section>
  <section id="questions">
{questions_html}
  </section>
  <div id="controls">
    <button id="assemble-btn"
            data-q-map='{q_letter_map_json}'
            data-golden="{golden_attr}">
      Assemble answers
    </button>
    <pre id="answer-output"></pre>
  </div>
</div>
<script>
{js}
</script>
</body>
</html>"""
