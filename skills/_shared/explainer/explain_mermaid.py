"""explainer/explain_mermaid.py — mermaid text from a diagram spec.

Public API:
    HEADER                          kind -> mermaid header line
    spec_mermaid(spec) -> str | None

spec_mermaid runs explain_spec.sanitize_spec first, the same gate that
explain_svg.spec_svg uses, so one spec gives both the SVG and the mermaid. An
unusable spec (or a raw svg / mermaid / html diagram) gives None, and the
caller omits the block. The model never writes mermaid.

Node ids are n0..nK in node order (a repeated node keeps its first id). The
label shown is labels.get(node, node), as in the SVG, escaped by
_escape_label.

  flow          flowchart LR, n0["label"], n0 --> n1
  decision      flowchart TD; the spec's edges when it has any, otherwise
                the first node links to every other node (hub fan-out)
  state         stateDiagram-v2, state "label" as n0, n0 --> n1
  before-after  flowchart LR, one classDef per status (explain_svg_ext
                STATUS_FILL colours), n0["label"]:::status
  sequence      sequenceDiagram, participant n0 as label, n0->>n1: label

Labels are escaped in one pass with mermaid entity codes: " becomes #quot;,
and # < > ` [ ] { } ( ) | ; become #<code>;. Escaping # too means a label
can not carry an entity of its own. Every whitespace run (newlines too)
becomes one space, so a label never starts a new statement. Mermaid decodes
the entities when it draws, so the reader sees the original text.

Stdlib only. Flat-import package — no __init__.py.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import explain_spec as _spec  # noqa: E402
from explain_spec_ext import STATUSES  # noqa: E402
from explain_svg_ext import STATUS_FILL  # noqa: E402

HEADER = {
    "flow": "flowchart LR",
    "decision": "flowchart TD",
    "state": "stateDiagram-v2",
    "before-after": "flowchart LR",
    "sequence": "sequenceDiagram",
}

_INDENT = "    "
_STROKE = "#495057"
_TEXT = "#212529"

# One pass (str.translate), so a code's own "#" and ";" are never re-escaped.
_ESCAPES = {'"': "#quot;"}
_ESCAPES.update({c: f"#{ord(c)};" for c in "#<>`[]{}()|;"})
_ESCAPE_TABLE = str.maketrans(_ESCAPES)


def _escape_label(text) -> str:
    """A mermaid-safe label: entity-escaped, on one line."""
    return " ".join(str(text).split()).translate(_ESCAPE_TABLE)


def _ids(nodes: list) -> dict:
    """node -> n<i>, in node order; a repeated node keeps its first id."""
    ids: dict = {}
    for node in nodes:
        ids.setdefault(node, f"n{len(ids)}")
    return ids


def _shown(sanitized: dict, node: str, nid: str) -> str:
    """The escaped label for a node; its id when the label is empty."""
    return _escape_label(sanitized["labels"].get(node, node)) or nid


def _arrows(pairs, ids: dict) -> list:
    """n0 --> n1 lines for each distinct [src, dst] pair, in order."""
    seen, lines = set(), []
    for src, dst in pairs:
        key = (ids[src], ids[dst])
        if key not in seen:
            seen.add(key)
            lines.append(f"{key[0]} --> {key[1]}")
    return lines


def _flow_nodes(sanitized: dict, ids: dict, classes: Optional[dict] = None) -> list:
    lines = []
    for node, nid in ids.items():
        suffix = f":::{classes[node]}" if classes else ""
        lines.append(f'{nid}["{_shown(sanitized, node, nid)}"]{suffix}')
    return lines


def _flow_body(sanitized: dict, ids: dict) -> list:
    return _flow_nodes(sanitized, ids) + _arrows(sanitized["edges"], ids)


def _decision_body(sanitized: dict, ids: dict) -> list:
    nodes = sanitized["nodes"]
    edges = sanitized["edges"]
    if edges:
        return _flow_nodes(sanitized, ids) + _arrows(edges, ids)
    star = [[nodes[0], n] for n in nodes[1:] if n != nodes[0]] if nodes else []
    return _flow_nodes(sanitized, ids) + _arrows(star, ids)


def _state_body(sanitized: dict, ids: dict) -> list:
    lines = [f'state "{_shown(sanitized, node, nid)}" as {nid}'
             for node, nid in ids.items()]
    return lines + _arrows(sanitized["edges"], ids)


def _before_after_body(sanitized: dict, ids: dict) -> list:
    lines = [f"classDef {s} fill:{STATUS_FILL[s]},stroke:{_STROKE},color:{_TEXT}"
             for s in STATUSES]
    lines += _flow_nodes(sanitized, ids, classes=sanitized["status"])
    return lines + _arrows(sanitized["edges"], ids)


def _sequence_body(sanitized: dict, ids: dict) -> list:
    lines = [f"participant {nid} as {_shown(sanitized, node, nid)}"
             for node, nid in ids.items()]
    for src, dst, label in sanitized["messages"]:
        lines.append(f"{ids[src]}->>{ids[dst]}: {_escape_label(label)}".rstrip())
    return lines


_BODY = {
    "flow": _flow_body,
    "decision": _decision_body,
    "state": _state_body,
    "before-after": _before_after_body,
    "sequence": _sequence_body,
}


def spec_mermaid(spec) -> Optional[str]:
    """Mermaid text for a diagram spec; None when the spec is unusable."""
    sanitized = _spec.sanitize_spec(spec)
    if sanitized is None:
        return None
    kind = sanitized["kind"]
    body = _BODY.get(kind)
    if body is None:
        return None
    ids = _ids(sanitized["nodes"])
    lines = [HEADER[kind]] + [_INDENT + ln for ln in body(sanitized, ids)]
    return "\n".join(lines)
