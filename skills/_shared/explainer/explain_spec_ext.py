"""explainer/explain_spec_ext.py — sanitize the before-after and sequence kinds.

Public API:
    KINDS       the two kinds this module sanitizes
    STATUSES    the closed before-after status enum
    sanitize_ext(spec, sanitize_label=None) -> Optional[dict]

explain_spec.sanitize_spec validates the kind, rejects raw-markup dicts and
dispatches these two kinds here. The shapes:

    before-after  {kind, nodes, edges, labels, status: {node: STATUSES[i]}}
                  Every kept node has a status; an unknown or missing status
                  is "existing"; a status key that is not a node is dropped.
    sequence      {kind, nodes, messages: [[src, dst, label], ...], labels}
                  Message order is kept; a message naming an unknown
                  participant or shorter than 3 items is dropped.

Nodes, edges and messages take the explain_spec_shape item shapes ({id,
label} node dicts; {from, to} / {source, target} edge dicts, plus "label"
for messages). A container id, endpoint or label gives None, and so does a
degenerate spec (explain_spec_shape.is_degenerate): every given link
dropped, or 2+ nodes and no link. A one-node before-after is kept.

Nodes are capped at MAX_NODES, edges and messages at MAX_EDGES, and every
string goes through the caller's label sanitizer (no html.escape here).

Stdlib only. Flat-import package — no __init__.py.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Optional

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import explain_spec_shape as _shape  # noqa: E402

KINDS = ("before-after", "sequence")
STATUSES = ("added", "changed", "removed", "existing")
_DEFAULT_STATUS = "existing"


def _status(raw, nodes: list, sanitize_label: Callable) -> dict:
    """One closed-enum status per kept node; anything else is "existing"."""
    given = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            given[sanitize_label(key)] = value
    return {n: given[n] if given.get(n) in STATUSES else _DEFAULT_STATUS
            for n in nodes}


def sanitize_ext(spec, sanitize_label: Optional[Callable] = None) -> Optional[dict]:
    """Sanitize a before-after or sequence spec; None when it is unusable."""
    # Read lazily: explain_spec imports this module, so a top-level import
    # would be circular. By call time explain_spec is fully loaded.
    import explain_spec as _spec

    if sanitize_label is None:
        sanitize_label = _spec._sanitize_label
    if not isinstance(spec, dict) or spec.get("kind") not in KINDS:
        return None
    raw_nodes = spec.get("nodes")
    if not isinstance(raw_nodes, list):
        return None

    kind = spec["kind"]
    entry = _shape.message_entry if kind == "sequence" else _shape.edge_entry
    raw_links = spec.get("messages" if kind == "sequence" else "edges")
    try:
        nodes, node_labels = _shape.sanitize_nodes(raw_nodes[:_spec.MAX_NODES],
                                                   sanitize_label)
        links, given = _shape.sanitize_links(raw_links, set(nodes), sanitize_label,
                                             _spec.MAX_EDGES, entry=entry)
        labels = _shape.sanitize_labels(spec.get("labels"), node_labels,
                                        sanitize_label)
    except _shape.ShapeError:
        return None
    if _shape.is_degenerate(kind, nodes, given, links):
        return None
    if kind == "sequence":
        return {"kind": kind, "nodes": nodes, "messages": links, "labels": labels}
    return {
        "kind": kind,
        "nodes": nodes,
        "edges": links,
        "labels": labels,
        "status": _status(spec.get("status"), nodes, sanitize_label),
    }
