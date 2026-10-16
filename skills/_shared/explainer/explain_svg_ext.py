"""explainer/explain_svg_ext.py — offline SVG for the before-after and sequence kinds.

Public API:
    STATUS_FILL                     status -> node fill, one per explain_spec_ext.STATUSES
    DRAW                            kind -> drawing function (used by explain_svg.spec_svg)
    before_after_svg(sanitized) -> str
    sequence_svg(sanitized)     -> str

Both functions take the dict explain_spec.sanitize_spec returns for their kind
(the explain_spec_ext shapes) and draw it with explain_svg's helpers (_esc,
_box, _line, _svg_open). explain_svg.spec_svg sanitizes first and dispatches
here, so call these directly only with an already-sanitized spec.

  before-after  boxes in a wrapped grid, each filled by its status, edges
                beneath them, and a key for the statuses that are drawn
  sequence      participant boxes across the top with dashed lifelines, and
                one labelled arrow per message, top to bottom in message order

Every label is escaped once, at draw time, by explain_svg._esc. Repeated node
ids draw once, at their first position.

Stdlib only. Flat-import package — no __init__.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# explain_svg imports this module lazily (inside spec_svg), so this top-level
# import is not circular.
from explain_spec_ext import STATUSES  # noqa: E402
from explain_svg import (  # noqa: E402
    _BOX_H, _BOX_W, _H_GAP, _PALETTE, _V_GAP,
    _box, _empty_svg, _esc, _line, _svg_open,
)

# Light tints so the dark label text stays readable on every status.
STATUS_FILL = {
    "added": "#b2f2bb",
    "changed": "#ffe066",
    "removed": "#ffa8a8",
    "existing": "#dee2e6",
}

_PAD = 16
_GRID_COLS = 4          # before-after boxes per row before wrapping
_KEY_H = 24             # height of the status key row
_KEY_ITEM_W = 80        # width of one swatch + status word in the key
_SWATCH = 12
_MSG_STROKE = "#495057"
_LIFELINE_STROKE = "#adb5bd"
_MSG_ROW_H = 30         # vertical step between sequence messages
_ARROW = 7              # arrowhead length
_SELF_LOOP_W = 24       # width of a self-message loop


def _unique(nodes: list) -> list:
    return list(dict.fromkeys(nodes))


# ---------------------------------------------------------------------------
# before-after — status-filled boxes in a wrapped grid
# ---------------------------------------------------------------------------

def _status_key(y: int, statuses: list) -> list:
    """Swatch + status word for each status drawn, in STATUSES order."""
    parts = []
    for i, status in enumerate(statuses):
        x = _PAD + i * _KEY_ITEM_W
        parts.append(
            f'<rect x="{x}" y="{y}" width="{_SWATCH}" height="{_SWATCH}" '
            f'fill="{STATUS_FILL[status]}" stroke="{_PALETTE["stroke"]}" '
            f'stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{x + _SWATCH + 4}" y="{y + _SWATCH - 2}" font-size="10" '
            f'fill="{_PALETTE["text"]}">{_esc(status)}</text>'
        )
    return parts


def before_after_svg(sanitized: dict) -> str:
    """Draw a sanitized before-after spec: each node's fill is its status."""
    nodes = _unique(sanitized["nodes"])
    if not nodes:
        return _empty_svg("Before/after")
    labels = sanitized["labels"]
    status = sanitized["status"]

    cols = min(len(nodes), _GRID_COLS)
    rows = -(-len(nodes) // cols)
    shown = [s for s in STATUSES if s in {status[n] for n in nodes}]
    grid_w = cols * _BOX_W + (cols - 1) * _H_GAP
    width = _PAD * 2 + max(grid_w, len(shown) * _KEY_ITEM_W)
    key_y = _PAD + rows * _BOX_H + (rows - 1) * _V_GAP + _PAD
    height = key_y + _KEY_H

    origin = {}
    for i, nid in enumerate(nodes):
        origin[nid] = (_PAD + (i % cols) * (_BOX_W + _H_GAP),
                       _PAD + (i // cols) * (_BOX_H + _V_GAP))

    parts = [_svg_open(width, height, "Before/after diagram")]
    # Edges first, centre to centre, so the boxes drawn on top cover the ends.
    for src, dst in sanitized["edges"]:
        if src != dst:
            (x1, y1), (x2, y2) = origin[src], origin[dst]
            parts.append(_line(x1 + _BOX_W // 2, y1 + _BOX_H // 2,
                               x2 + _BOX_W // 2, y2 + _BOX_H // 2))
    for nid in nodes:
        x, y = origin[nid]
        parts += _box(x, y, labels.get(nid, nid), STATUS_FILL[status[nid]],
                      _PALETTE["stroke"], _PALETTE["text"])
    parts += _status_key(key_y, shown)
    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# sequence — participants, lifelines, ordered messages
# ---------------------------------------------------------------------------

def _lifeline(x, y1, y2) -> str:
    return (
        f'<line x1="{x}" y1="{y1}" x2="{x}" y2="{y2}" '
        f'stroke="{_LIFELINE_STROKE}" stroke-width="1" stroke-dasharray="4 3"/>'
    )


def _arrowhead(x, y, direction: int) -> str:
    """Triangle with its tip at (x, y), pointing right (1) or left (-1)."""
    back = x - direction * _ARROW
    return (
        f'<polygon points="{x},{y} {back},{y - 4} {back},{y + 4}" '
        f'fill="{_MSG_STROKE}"/>'
    )


def _msg_label(x, y, label: str, anchor: str) -> str:
    return (
        f'<text x="{x}" y="{y - 6}" text-anchor="{anchor}" font-size="10" '
        f'fill="{_PALETTE["text"]}">{_esc(label)}</text>'
    )


def _message(sx, dx, y, label: str) -> list:
    """One message arrow from lifeline sx to lifeline dx at height y."""
    if sx == dx:  # a self-message loops out to the right and back
        right = sx + _SELF_LOOP_W
        return [_line(sx, y - 8, right, y - 8, _MSG_STROKE),
                _line(right, y - 8, right, y, _MSG_STROKE),
                _line(right, y, sx, y, _MSG_STROKE),
                _arrowhead(sx, y, -1),
                _msg_label(right + 4, y - 4, label, "start")]
    direction = 1 if dx > sx else -1
    return [_line(sx, y, dx, y, _MSG_STROKE),
            _arrowhead(dx, y, direction),
            _msg_label((sx + dx) // 2, y, label, "middle")]


def sequence_svg(sanitized: dict) -> str:
    """Draw a sanitized sequence spec: messages top to bottom, in order."""
    nodes = _unique(sanitized["nodes"])
    if not nodes:
        return _empty_svg("Sequence")
    labels = sanitized["labels"]
    messages = sanitized["messages"]

    centre = {nid: _PAD + i * (_BOX_W + _H_GAP) + _BOX_W // 2
              for i, nid in enumerate(nodes)}
    self_room = 80 if any(src == dst for src, dst, _ in messages) else 0
    width = _PAD * 2 + len(nodes) * _BOX_W + (len(nodes) - 1) * _H_GAP + self_room
    first_y = _PAD + _BOX_H + _MSG_ROW_H
    bottom = first_y + max(0, len(messages) - 1) * _MSG_ROW_H + _PAD
    height = bottom + _PAD

    parts = [_svg_open(width, height, "Sequence diagram")]
    for nid in nodes:
        cx = centre[nid]
        parts += _box(cx - _BOX_W // 2, _PAD, labels.get(nid, nid),
                      _PALETTE["node_fill"], _PALETTE["stroke"],
                      _PALETTE["node_text"])
        parts.append(_lifeline(cx, _PAD + _BOX_H, bottom))
    for k, (src, dst, label) in enumerate(messages):
        parts += _message(centre[src], centre[dst], first_y + k * _MSG_ROW_H, label)
    parts.append("</svg>")
    return "".join(parts)


DRAW = {"before-after": before_after_svg, "sequence": sequence_svg}
