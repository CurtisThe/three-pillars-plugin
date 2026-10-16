"""explainer/explain_svg.py — spec-driven inline SVG for EXPLAIN diagrams.

Public API:
    spec_svg(spec) -> str

Draws a diagram_spec into a well-formed, 0-KB, external-ref-free <svg>.
ALWAYS calls explain_spec.sanitize_spec first (defense-in-depth), so even
a raw/hostile spec passed directly is safe.  A None or unusable spec
returns an empty-but-valid SVG.

Kinds drawn here (before-after and sequence draw in explain_svg_ext):
  flow     — horizontal step chain (boxes + connector lines)
  decision — diamond root node + branch labels
  state    — labeled circular nodes with transition edges

All output passes briefing.assert_offline. Reuses live_svg conventions:
  _svg_open / _esc / _PALETTE.

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

import explain_spec as _spec  # noqa: E402

# ---------------------------------------------------------------------------
# Palette / helpers (mirrors live_svg conventions)
# ---------------------------------------------------------------------------

_PALETTE = {
    "edge": "#999",
    "text": "#212529",
    "bg": "#f8f9fa",
    "stroke": "#1a5ba8",
    "node_fill": "#4e91e8",
    "node_text": "#ffffff",
    "decision_fill": "#fd7e14",
    "state_fill": "#6f42c1",
}


def _esc(value) -> str:
    return _html.escape(str(value), quote=True)


def _svg_open(width: int, height: int, label: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width}" height="{height}" '
        f'role="img" aria-label="{_esc(label)}">'
        f'<rect width="{width}" height="{height}" fill="{_PALETTE["bg"]}"/>'
    )


def _empty_svg(label: str = "Diagram") -> str:
    """Return a minimal empty-but-valid SVG with an explanatory text."""
    parts = [_svg_open(200, 40, label)]
    parts.append(
        f'<text x="100" y="25" text-anchor="middle" '
        f'font-size="12" fill="{_PALETTE["text"]}">{_esc(label)}</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Box/edge drawing primitives
# ---------------------------------------------------------------------------

_BOX_W = 100
_BOX_H = 32
_BOX_RX = 6
_H_GAP = 20   # horizontal gap between flow boxes
_V_GAP = 30   # vertical gap between state nodes


def _box(x, y, label: str, fill: str, stroke: str, text_fill: str) -> list:
    """Return SVG parts for a rounded rectangle + centred label."""
    parts = []
    parts.append(
        f'<rect x="{x}" y="{y}" width="{_BOX_W}" height="{_BOX_H}" '
        f'rx="{_BOX_RX}" fill="{fill}" stroke="{stroke}" stroke-width="1"/>'
    )
    parts.append(
        f'<text x="{x + _BOX_W // 2}" y="{y + _BOX_H // 2 + 4}" '
        f'text-anchor="middle" font-size="11" fill="{text_fill}">'
        f'{_esc(label)}</text>'
    )
    return parts


def _line(x1, y1, x2, y2, stroke: str = "") -> str:
    stroke = stroke or _PALETTE["edge"]
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
        f'stroke="{stroke}" stroke-width="1.5"/>'
    )


def _arc(x1, y1, x2, y2, stroke: str = "") -> str:
    """Curved connector for a backward/feedback edge (dst left of src).

    A straight horizontal line for a backward edge would be drawn right-to-left
    over the boxes and read as a forward connector; instead bow a quadratic
    curve ABOVE the row so the feedback arc (e.g. a retry arrow) is visible.
    Backward edges were previously dropped silently by the ``x2 > x1`` guard.
    """
    stroke = stroke or _PALETTE["edge"]
    midx = (x1 + x2) / 2
    ctrl_y = min(y1, y2) - 18  # control point above the row → upward bow
    return (
        f'<path d="M{x1},{y1} Q{midx},{ctrl_y} {x2},{y2}" '
        f'fill="none" stroke="{stroke}" stroke-width="1.5"/>'
    )


# ---------------------------------------------------------------------------
# Flow kind — horizontal step chain
# ---------------------------------------------------------------------------

def _flow_svg(sanitized: dict) -> str:
    nodes = sanitized["nodes"]
    edges = sanitized["edges"]
    labels = sanitized["labels"]

    n = len(nodes)
    if n == 0:
        return _empty_svg("Flow")

    # Lay out horizontally: padding on each side. Extra top room above the row
    # so a backward feedback arc bowing upward stays inside the viewport.
    pad = 16
    top_pad = pad + 22
    width = pad * 2 + n * _BOX_W + max(0, n - 1) * _H_GAP
    height = _BOX_H + top_pad + pad + 20   # +20 for edge arrow room

    parts = [_svg_open(width, height, "Flow diagram")]

    # Compute box centres for edge drawing
    cx = {}  # node_id -> centre x
    cy_mid = top_pad + _BOX_H // 2

    for i, nid in enumerate(nodes):
        x = pad + i * (_BOX_W + _H_GAP)
        cx[nid] = x + _BOX_W // 2
        label = labels.get(nid, nid)
        parts += _box(x, top_pad, label, _PALETTE["node_fill"],
                      _PALETTE["stroke"], _PALETTE["node_text"])

    # Draw edges (only between known nodes — already filtered by sanitize_spec).
    # Forward edges are straight connectors; backward/feedback edges are drawn
    # as an upward-bowing arc instead of being silently dropped.
    for src, dst in edges:
        if src in cx and dst in cx:
            if cx[dst] > cx[src]:
                # forward — horizontal connector between the facing box edges
                x1 = cx[src] + _BOX_W // 2
                x2 = cx[dst] - _BOX_W // 2
                parts.append(_line(x1, cy_mid, x2, cy_mid))
            else:
                # backward/feedback — arc from src's left edge to dst's right
                x1 = cx[src] - _BOX_W // 2
                x2 = cx[dst] + _BOX_W // 2
                parts.append(_arc(x1, cy_mid, x2, cy_mid))

    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Decision kind — diamond root + branch labels
# ---------------------------------------------------------------------------

_DIAMOND_HALF = 20  # half-size of the diamond


def _diamond(cx, cy, fill: str, stroke: str) -> str:
    h = _DIAMOND_HALF
    points = f"{cx},{cy - h} {cx + h},{cy} {cx},{cy + h} {cx - h},{cy}"
    return (
        f'<polygon points="{points}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="1"/>'
    )


def _decision_svg(sanitized: dict) -> str:
    nodes = sanitized["nodes"]
    edges = sanitized["edges"]
    labels = sanitized["labels"]

    if not nodes:
        return _empty_svg("Decision")

    # First node is the root decision; others are branch outcomes
    root = nodes[0]
    branches = nodes[1:]

    pad = 20
    branch_cols = max(1, len(branches))
    width = max(200, pad * 2 + branch_cols * (_BOX_W + _H_GAP))
    height = 140

    parts = [_svg_open(width, height, "Decision diagram")]

    # Root diamond, centred top
    root_cx = width // 2
    root_cy = pad + _DIAMOND_HALF
    parts.append(_diamond(root_cx, root_cy, _PALETTE["decision_fill"],
                           _PALETTE["stroke"]))
    root_label = labels.get(root, root)
    parts.append(
        f'<text x="{root_cx}" y="{root_cy + 4}" '
        f'text-anchor="middle" font-size="10" fill="#fff">{_esc(root_label)}</text>'
    )

    # Branch boxes in a row below
    branch_y = root_cy + _DIAMOND_HALF + _V_GAP
    total_branch_w = branch_cols * _BOX_W + max(0, branch_cols - 1) * _H_GAP
    branch_x0 = (width - total_branch_w) // 2

    # Connector anchors per node: root anchors at the diamond bottom; each
    # branch anchors at its box-top centre. Built so model-specified `edges`
    # (previously extracted then ignored — every diagram rendered as an
    # all-from-root star) can be honored.
    anchors = {root: (root_cx, root_cy + _DIAMOND_HALF)}
    for i, bid in enumerate(branches):
        bx = branch_x0 + i * (_BOX_W + _H_GAP)
        blabel = labels.get(bid, bid)
        parts += _box(bx, branch_y, blabel, _PALETTE["node_fill"],
                      _PALETTE["stroke"], _PALETTE["node_text"])
        # First occurrence wins if a branch id repeats (anchor is stable).
        anchors.setdefault(bid, (bx + _BOX_W // 2, branch_y))

    # Real edges first: the hub star (root to every branch) is drawn only when
    # the spec gives no edges. Otherwise draw the given edges; an edge between
    # two branch boxes is an arc so it does not lie along the shared top edge.
    root_anchor = anchors[root]
    if not edges:
        for bid in branches:
            bcx, bcy = anchors[bid]
            parts.append(_line(root_anchor[0], root_anchor[1], bcx, bcy))
    drawn = set()
    for src, dst in edges:
        if src in anchors and dst in anchors and (src, dst) not in drawn:
            x1, y1 = anchors[src]
            x2, y2 = anchors[dst]
            draw = _line if root in (src, dst) else _arc
            parts.append(draw(x1, y1, x2, y2))
            drawn.add((src, dst))

    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# State kind — labeled circle nodes + transition edges
# ---------------------------------------------------------------------------

_CIRCLE_R = 22


def _circle_node(cx, cy, label: str, fill: str, stroke: str) -> list:
    parts = []
    parts.append(
        f'<circle cx="{cx}" cy="{cy}" r="{_CIRCLE_R}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="1"/>'
    )
    parts.append(
        f'<text x="{cx}" y="{cy + 4}" text-anchor="middle" '
        f'font-size="10" fill="#fff">{_esc(label)}</text>'
    )
    return parts


def _state_svg(sanitized: dict) -> str:
    nodes = sanitized["nodes"]
    edges = sanitized["edges"]
    labels = sanitized["labels"]

    n = len(nodes)
    if n == 0:
        return _empty_svg("State")

    pad = 30
    # Extra top room above the row so a backward feedback arc bowing upward
    # stays inside the viewport.
    top_pad = pad + 22
    # Lay out in a single horizontal row
    node_spacing = _CIRCLE_R * 2 + 50
    width = pad * 2 + n * node_spacing
    height = _CIRCLE_R * 2 + top_pad + pad

    parts = [_svg_open(width, height, "State diagram")]

    # Compute node centre positions
    centres = {}
    cy = top_pad + _CIRCLE_R
    for i, nid in enumerate(nodes):
        cx = pad + i * node_spacing + _CIRCLE_R
        centres[nid] = (cx, cy)
        nlabel = labels.get(nid, nid)
        parts += _circle_node(cx, cy, nlabel, _PALETTE["state_fill"],
                               _PALETTE["stroke"])

    # Draw transition edges between known nodes. Forward transitions are
    # straight lines; backward/feedback transitions (dst left of src) are drawn
    # as an upward-bowing arc instead of being silently dropped.
    for src, dst in edges:
        if src in centres and dst in centres:
            sx, sy = centres[src]
            dx, dy = centres[dst]
            if dx > sx:
                # forward — line from right edge of src to left edge of dst
                parts.append(_line(sx + _CIRCLE_R, sy, dx - _CIRCLE_R, dy))
            else:
                # backward/feedback — arc from src's left edge to dst's right
                parts.append(_arc(sx - _CIRCLE_R, sy, dx + _CIRCLE_R, dy))

    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def spec_svg(spec) -> str:
    """Draw a diagram_spec into a well-formed, 0-KB, external-ref-free <svg>.

    Always calls explain_spec.sanitize_spec first (defense-in-depth).
    A None spec or an unusable spec (bad kind, sanitize_spec returns None)
    yields an empty-but-valid SVG.

    Dispatch:
      flow     -> _flow_svg
      decision -> _decision_svg
      state    -> _state_svg
      before-after, sequence -> explain_svg_ext.DRAW

    Output always passes briefing.assert_offline().
    """
    sanitized = _spec.sanitize_spec(spec)
    if sanitized is None:
        return _empty_svg()

    kind = sanitized["kind"]
    if kind == "flow":
        return _flow_svg(sanitized)
    elif kind == "decision":
        return _decision_svg(sanitized)
    elif kind == "state":
        return _state_svg(sanitized)
    # before-after / sequence draw in explain_svg_ext, imported here because it
    # imports this module's helpers. Any other kind (sanitize_spec enforces
    # ALLOWED_KINDS, so none should reach here) gets the empty SVG.
    import explain_svg_ext
    draw = explain_svg_ext.DRAW.get(kind)
    return draw(sanitized) if draw else _empty_svg()
