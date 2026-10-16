"""explainer/explain_html.py — the self-contained offline HTML page.

Public API:
    render_html(env, *, head, title) -> str

Renders one explain envelope (any kind) into a single HTML document with an
inline <style> and each diagram_specs entry drawn inline by
explain_svg.spec_svg. The page names the briefed head and holds, in order:

    header           title, kind and "Briefed head: <head>"
    facts-only label when env["facts_only"] is True (a visible label)
    style note       when env["style_note"] is a non-empty string
    summary          ste_summary text and its refs
    diagram notes    one <p class="diagram-note"> per string in
                     env["diagram_notes"] (a dropped diagram: "diagram
                     omitted: <reason>"); none when the key is absent or empty
    diagrams         one <figure> per diagram_specs entry
    sections         one element carrying data-section="<id>" per envelope
                     section, in envelope order: title, then each item's
                     text, a "Recommended" badge when the item has
                     "recommended": true, and its refs
    confidence note  confidence_note text and its refs

Escaping: every model string (kind, texts, titles, section ids, refs, the
style note, the diagram notes) goes through explain_text.safe_text, which runs
html.escape once and neutralizes every assert_offline token. Model strings get
no second escape pass. The caller's head and title are not model text: they get one
html.escape. Diagram labels are sanitized and escaped by spec_svg.

The page passes explain_offline.assert_offline; render_html checks this on
its own output before it returns. It never mutates env.

Stdlib only. Flat-import package — no __init__.py.
"""
from __future__ import annotations

import html as _html
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import explain_offline  # noqa: E402
from explain_svg import spec_svg  # noqa: E402
from explain_text import safe_text  # noqa: E402

FACTS_ONLY_LABEL = ("Facts only: the draft did not pass the checks, so this "
                    "page shows only the cited evidence.")

_CSS = """
body { font-family: system-ui, sans-serif; color: #212529; background: #fff;
       max-width: 52rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }
header { border-bottom: 2px solid #1a5ba8; margin-bottom: 1rem; }
h1 { font-size: 1.5rem; margin: 0 0 0.25rem; }
h2 { font-size: 1.15rem; margin: 1.5rem 0 0.5rem; color: #1a5ba8; }
.meta { color: #495057; font-size: 0.9rem; }
.label { padding: 0.5rem 0.75rem; border-radius: 4px; font-weight: 600; }
.facts-only { background: #fff3cd; border: 1px solid #fd7e14; }
.style-note { background: #e9ecef; border: 1px solid #adb5bd; font-weight: 400; }
.summary { font-size: 1.05rem; }
.diagram-note { color: #495057; font-style: italic; margin: 0.5rem 0; }
.refs { color: #6c757d; font-size: 0.85rem; margin-left: 0.5rem; }
.badge { background: #198754; color: #fff; border-radius: 3px;
         padding: 0 0.4rem; font-size: 0.8rem; margin-left: 0.5rem; }
figure.diagram { margin: 1rem 0; overflow-x: auto; }
footer { border-top: 1px solid #dee2e6; margin-top: 2rem; color: #495057; }
code { background: #f1f3f5; padding: 0 0.2rem; border-radius: 3px; }
"""


def _refs(block) -> str:
    """The refs of a {text, refs} block as inline code spans ("" if none)."""
    refs = block.get("refs") if isinstance(block, dict) else None
    if not isinstance(refs, list) or not refs:
        return ""
    codes = ", ".join(f"<code>{safe_text(r)}</code>" for r in refs)
    return f'<span class="refs">{codes}</span>'


def _text(block) -> str:
    text = block.get("text") if isinstance(block, dict) else None
    return safe_text(text) if text is not None else ""


def _item(item) -> str:
    badge = ""
    if isinstance(item, dict) and item.get("recommended") is True:
        badge = '<span class="badge">Recommended</span>'
    return f"<li><span>{_text(item)}</span>{badge}{_refs(item)}</li>"


def _section(sec) -> str:
    if not isinstance(sec, dict):
        return ""
    items = sec.get("items")
    lis = "".join(_item(i) for i in items) if isinstance(items, list) else ""
    return (f'<section data-section="{safe_text(sec.get("id", ""))}">'
            f'<h2>{safe_text(sec.get("title", ""))}</h2><ul>{lis}</ul></section>')


def _labels(env: dict) -> list:
    parts = []
    if env.get("facts_only") is True:
        parts.append(f'<p class="label facts-only">{_html.escape(FACTS_ONLY_LABEL)}</p>')
    note = env.get("style_note")
    if isinstance(note, str) and note:
        parts.append(f'<p class="label style-note">{safe_text(note)}</p>')
    return parts


def _diagram_notes(env: dict) -> list:
    notes = env.get("diagram_notes")
    notes = notes if isinstance(notes, list) else []
    return [f'<p class="diagram-note">{safe_text(n)}</p>'
            for n in notes if isinstance(n, str) and n.strip()]


def render_html(env, *, head, title) -> str:
    """One self-contained offline HTML page for ``env``; see the module docstring."""
    env = env if isinstance(env, dict) else {}
    esc_title = _html.escape(str(title))
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{esc_title}</title>",
        f"<style>{_CSS}</style>",
        "</head><body>",
        f"<header><h1>{esc_title}</h1>",
        f'<p class="meta">Kind: <code>{safe_text(env.get("kind", ""))}</code>'
        f' &middot; Briefed head: <code>{_html.escape(str(head))}</code></p>',
        "</header>",
    ]
    parts += _labels(env)
    summary = env.get("ste_summary")
    parts.append(f'<p class="summary">{_text(summary)}{_refs(summary)}</p>')
    parts += _diagram_notes(env)
    specs = env.get("diagram_specs")
    for spec in specs if isinstance(specs, list) else []:
        parts.append(f'<figure class="diagram">{spec_svg(spec)}</figure>')
    sections = env.get("sections")
    for sec in sections if isinstance(sections, list) else []:
        parts.append(_section(sec))
    note = env.get("confidence_note")
    parts.append(f"<footer><p>{_text(note)}{_refs(note)}</p></footer>")
    parts.append("</body></html>")
    page = "\n".join(parts)
    explain_offline.assert_offline(page)
    return page
