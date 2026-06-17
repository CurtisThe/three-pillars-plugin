"""html_briefing/svg.py — hand-rolled inline SVG visuals.

Public API:
  wave_topology_svg(wave_model) -> str      wave/parallelism topology
  collision_matrix_svg(wave_model) -> str   pairwise file-collision matrix
  progress_bar_svg(wave_model) -> str       N-done/M-total progress bar

All return a well-formed <svg …>…</svg> string.
Stdlib only. No external hrefs, xlink:href, <image> tags, or url() references.
Flat-import package — no __init__.py.
"""
from __future__ import annotations

import html as _html


# ---------------------------------------------------------------------------
# Colour / layout palette
# ---------------------------------------------------------------------------

_PALETTE = {
    "node_fill": "#4e91e8",
    "node_stroke": "#1a5ba8",
    "edge": "#999",
    "text": "#212529",
    "bg": "#f8f9fa",
    "collision": "#e84e4e",
    "no_collision": "#d4edda",
    "cell_stroke": "#ced4da",
    "progress_fill": "#28a745",
    "progress_bg": "#e9ecef",
}

_W = 480   # default SVG width
_H_NODE = 40
_RADIUS = 18


def _attr(value: str) -> str:
    return _html.escape(str(value), quote=True)


# ---------------------------------------------------------------------------
# wave_topology_svg
# ---------------------------------------------------------------------------

def wave_topology_svg(wave_model) -> str:
    """Return an SVG showing seed nodes grouped into parallel/serial waves.

    wave_model has:
      .seeds: list of seed names (str)
      .waves: list of lists of seed names (outer = serial order, inner = parallel)
    """
    seeds = list(getattr(wave_model, "seeds", []))
    waves = list(getattr(wave_model, "waves", []))

    if not waves and seeds:
        waves = [seeds]

    wave_count = len(waves)
    col_width = max(_W // max(wave_count, 1), 80)
    svg_width = col_width * wave_count + 40
    max_rows = max((len(w) for w in waves), default=1)
    svg_height = max_rows * (_H_NODE + 20) + 60

    nodes = []   # (cx, cy, label)
    edges = []   # (x1,y1, x2,y2)

    prev_wave_centers = []
    for wi, wave in enumerate(waves):
        cx = 20 + wi * col_width + col_width // 2
        row_count = len(wave)
        cur_centers = []
        for ri, name in enumerate(wave):
            cy = 40 + ri * (_H_NODE + 20)
            nodes.append((cx, cy, str(name)))
            cur_centers.append((cx, cy))
        # Serial edges: connect every node in prev_wave to every node in cur_wave
        for px, py in prev_wave_centers:
            for nx, ny in cur_centers:
                edges.append((px, py, nx, ny))
        prev_wave_centers = cur_centers

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{svg_width}" height="{svg_height}" '
        f'role="img" aria-label="Wave topology">'
    ]
    lines.append(f'<rect width="{svg_width}" height="{svg_height}" fill="{_PALETTE["bg"]}"/>')

    for x1, y1, x2, y2 in edges:
        lines.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="{_PALETTE["edge"]}" stroke-width="1.5"/>'
        )

    for cx, cy, label in nodes:
        e_label = _attr(label)
        lines.append(
            f'<circle cx="{cx}" cy="{cy}" r="{_RADIUS}" '
            f'fill="{_PALETTE["node_fill"]}" stroke="{_PALETTE["node_stroke"]}" '
            f'stroke-width="2"/>'
        )
        lines.append(
            f'<text x="{cx}" y="{cy}" text-anchor="middle" dominant-baseline="central" '
            f'font-size="10" fill="#fff" font-family="monospace">'
            f'{e_label[:12]}</text>'
        )

    lines.append('</svg>')
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# collision_matrix_svg
# ---------------------------------------------------------------------------

def collision_matrix_svg(wave_model) -> str:
    """Return an SVG grid showing pairwise file-collision pairs.

    wave_model has:
      .seeds: list of seed names
      .collisions: set/list of frozensets or 2-tuples of seed name pairs
    """
    seeds = list(getattr(wave_model, "seeds", []))
    collisions_raw = getattr(wave_model, "collisions", [])
    collision_pairs = set()
    for pair in collisions_raw:
        items = list(pair)
        if len(items) == 2:
            collision_pairs.add((items[0], items[1]))
            collision_pairs.add((items[1], items[0]))

    n = len(seeds)
    if n == 0:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40"><text x="4" y="20">—</text></svg>'

    label_w = 100
    cell = 30
    svg_w = label_w + n * cell + 10
    svg_h = label_w + n * cell + 10

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{svg_w}" height="{svg_h}" '
        f'role="img" aria-label="Collision matrix">'
    ]
    lines.append(f'<rect width="{svg_w}" height="{svg_h}" fill="{_PALETTE["bg"]}"/>')

    # Column headers (rotated text approximation — just use short name)
    for ci, name in enumerate(seeds):
        x = label_w + ci * cell + cell // 2
        e_name = _attr(name[:8])
        lines.append(
            f'<text x="{x}" y="{label_w - 4}" text-anchor="end" '
            f'font-size="9" fill="{_PALETTE["text"]}" '
            f'transform="rotate(-45 {x} {label_w - 4})">'
            f'{e_name}</text>'
        )

    for ri, row_name in enumerate(seeds):
        y = label_w + ri * cell + cell // 2
        e_row = _attr(row_name[:12])
        lines.append(
            f'<text x="{label_w - 4}" y="{y + 4}" '
            f'text-anchor="end" font-size="9" fill="{_PALETTE["text"]}">'
            f'{e_row}</text>'
        )
        for ci, col_name in enumerate(seeds):
            cx = label_w + ci * cell
            cy = label_w + ri * cell
            if row_name == col_name:
                fill = "#e9ecef"
            elif (row_name, col_name) in collision_pairs:
                fill = _PALETTE["collision"]
            else:
                fill = _PALETTE["no_collision"]
            lines.append(
                f'<rect x="{cx}" y="{cy}" width="{cell}" height="{cell}" '
                f'fill="{fill}" stroke="{_PALETTE["cell_stroke"]}" stroke-width="0.5"/>'
            )

    lines.append('</svg>')
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# progress_bar_svg
# ---------------------------------------------------------------------------

def progress_bar_svg(wave_model) -> str:
    """Return an SVG progress bar for N-done / M-total.

    wave_model has:
      .done: int
      .total: int
    """
    done = int(getattr(wave_model, "done", 0))
    total = int(getattr(wave_model, "total", 1))
    total = max(total, 1)  # avoid division by zero
    done = max(0, min(done, total))

    bar_w = 400
    bar_h = 28
    svg_w = bar_w + 20
    svg_h = bar_h + 40

    fill_w = int(bar_w * done / total)
    pct = int(100 * done / total)

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{svg_w}" height="{svg_h}" '
        f'role="img" aria-label="Progress {done} of {total}">'
    ]
    lines.append(f'<rect width="{svg_w}" height="{svg_h}" fill="{_PALETTE["bg"]}"/>')

    # Background bar
    lines.append(
        f'<rect x="10" y="10" width="{bar_w}" height="{bar_h}" '
        f'rx="4" fill="{_PALETTE["progress_bg"]}" stroke="{_PALETTE["cell_stroke"]}" stroke-width="1"/>'
    )
    # Fill bar
    if fill_w > 0:
        lines.append(
            f'<rect x="10" y="10" width="{fill_w}" height="{bar_h}" '
            f'rx="4" fill="{_PALETTE["progress_fill"]}"/>'
        )
    # Label
    lines.append(
        f'<text x="{10 + bar_w // 2}" y="{10 + bar_h + 18}" '
        f'text-anchor="middle" font-size="12" fill="{_PALETTE["text"]}">'
        f'{done}/{total} ({pct}%)</text>'
    )
    lines.append('</svg>')
    return "\n".join(lines)
