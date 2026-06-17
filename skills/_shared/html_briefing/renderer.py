"""html_briefing/renderer.py — per-seed cards + form-control renderer.

Public API:
  render_cards(seeds) -> str        HTML fragment with one card per seed
  render_questions(model) -> str    HTML fragment with form controls

Stdlib only. Flat-import package — no __init__.py.
"""
from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SeedCard:
    """Per-seed briefing card data."""
    name: str
    brief: str
    weight_class: str
    badges: list          # list[str] — e.g. ["collision:design-b", "chokepoint"]
    branch: str
    sha: str
    probe_banner: Optional[str]
    premise_refresh_banner: Optional[str]


# ---------------------------------------------------------------------------
# Card renderer
# ---------------------------------------------------------------------------

def render_cards(seeds: list) -> str:
    """Return an HTML fragment with one card per SeedCard.

    All user data is HTML-escaped. No external resources.
    """
    parts = []
    for seed in seeds:
        parts.append(_render_card(seed))
    return "\n".join(parts)


def _render_card(seed: SeedCard) -> str:
    e = html.escape
    badges_html = "".join(
        f'<span class="badge">{e(b)}</span>' for b in seed.badges
    )
    probe = (
        f'<div class="banner probe">{e(seed.probe_banner)}</div>'
        if seed.probe_banner else ""
    )
    premise = (
        f'<div class="banner premise">{e(seed.premise_refresh_banner)}</div>'
        if seed.premise_refresh_banner else ""
    )
    return (
        f'<div class="seed-card" data-name="{e(seed.name)}">'
        f'<h2 class="seed-name">{e(seed.name)}</h2>'
        f'<p class="brief">{e(seed.brief)}</p>'
        f'<div class="meta">'
        f'<span class="weight-class">{e(seed.weight_class)}</span>'
        f'<span class="branch-sha">{e(seed.branch)} @ {e(seed.sha)}</span>'
        f'</div>'
        f'<div class="badges">{badges_html}</div>'
        f'{probe}{premise}'
        f'</div>'
    )


# ---------------------------------------------------------------------------
# Question / form-control renderer
# ---------------------------------------------------------------------------

def render_questions(model) -> str:
    """Return an HTML fragment with form controls for each question.

    - single-select → <input type="radio"> group; default option pre-checked.
    - multi-select  → <input type="checkbox"> group; default options pre-checked.
    - free-text     → <input type="text"> with default as value.

    All text is HTML-escaped. No external resources.
    """
    parts = []
    for q in sorted(model.questions, key=lambda q: q.number):
        parts.append(_render_question(q))
    return "\n".join(parts)


def _render_question(q) -> str:
    e = html.escape
    label = f'<div class="question" data-num="{q.number}" data-kind="{e(q.kind)}">'
    label += f'<p class="q-label">Q{q.number}</p>'

    if q.kind == "single":
        controls = _render_single(q)
    elif q.kind == "multi":
        controls = _render_multi(q)
    else:
        controls = _render_free(q)

    return label + controls + "</div>"


def _render_single(q) -> str:
    e = html.escape
    parts = []
    for letter, label in q.options:
        checked = ' checked' if letter == q.default else ''
        input_id = f"q{q.number}-{e(letter)}"
        parts.append(
            f'<label>'
            f'<input type="radio" name="q{q.number}" id="{input_id}" '
            f'value="{e(letter)}"{checked}> {e(label)}'
            f'</label>'
        )
    return "<div>" + "".join(parts) + "</div>"


def _render_multi(q) -> str:
    e = html.escape
    default_set = set(q.default)
    parts = []
    for letter, label in q.options:
        checked = ' checked' if letter in default_set else ''
        input_id = f"q{q.number}-{e(letter)}"
        parts.append(
            f'<label>'
            f'<input type="checkbox" name="q{q.number}" id="{input_id}" '
            f'value="{e(letter)}"{checked}> {e(label)}'
            f'</label>'
        )
    return "<div>" + "".join(parts) + "</div>"


def _render_free(q) -> str:
    e = html.escape
    return (
        f'<div>'
        f'<input type="text" name="q{q.number}" '
        f'value="{e(q.default)}">'
        f'</div>'
    )
