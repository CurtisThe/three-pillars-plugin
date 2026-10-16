"""explainer/explain_diagram_check.py — deterministic diagram check with reasons.

Public API:
    REASONS             {slug: plain sentence} for every reason problem() gives
    reason_text(slug)   -> the sentence for a slug (a generic one if unknown)
    problem(spec)       -> Optional[str]: a REASONS slug, or None when the
                           diagram passes

problem() is a pure check on a raw diagram_spec. It runs explain_spec's
sanitize_spec first. When that gives None, it reads the raw spec through
explain_spec_shape to name the cause:

    not-a-spec          not a JSON object (or an empty one)
    raw-markup          a string, or an svg / mermaid / html key
    bad-kind            kind missing or not in ALLOWED_KINDS
    bad-shape           nodes is not a list, or a container (list or dict)
                        stands where an id, endpoint or label belongs
    all-edges-dropped   edges (messages) were given and every one was dropped
    no-edges            a flow, state, before-after or sequence with 2+ nodes
                        and no edge (message)

When sanitize_spec keeps the spec, problem() checks the sanitized spec:

    dict-label          a node, label or message label holds a dict repr
                        (the markers in _DICT_MARKERS)
    too-few-nodes       a flow, state or sequence with fewer than 2 nodes
    orphan-node         a node (sequence: participant) no edge (message)
                        touches; a decision with no edges at all is a hub
                        and passes, as does a one-node before-after

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
import explain_spec_shape as _shape  # noqa: E402

REASONS = {
    "not-a-spec": "The diagram is not a JSON object with a kind and nodes.",
    "raw-markup": "The diagram is raw markup (svg, mermaid or html), not a spec.",
    "bad-kind": "The diagram kind is missing or is not one of the allowed kinds.",
    "bad-shape": "The diagram has a nodes list, edge, or label in a shape the "
                 "renderer cannot use.",
    "all-edges-dropped": "Every edge names a node that is not in the nodes list.",
    "no-edges": "The diagram has several nodes but no edge to connect them.",
    "too-few-nodes": "The diagram has fewer than two nodes.",
    "orphan-node": "A node has no edge, so it is not connected to the diagram.",
    "dict-label": "A node or label shows a dict or list text, such as "
                  "{'id': 'a'}, in place of a name.",
}
_GENERIC = "The diagram is not usable."

# Substrings that show a dict or list repr was str()-ed into a label.
_DICT_MARKERS = ("{'", "'id':", '{"', '"id":')
_PAIR_KINDS = ("flow", "state", "sequence")   # need 2+ nodes to mean anything


def reason_text(slug: str) -> str:
    """The plain sentence for a reason slug; a generic one for an unknown slug."""
    return REASONS.get(slug, _GENERIC)


def _links_key(kind) -> str:
    return "messages" if kind == "sequence" else "edges"


def _why_unusable(spec) -> str:
    """Name why sanitize_spec returned None for this raw spec."""
    if isinstance(spec, str):
        return "raw-markup"
    if not isinstance(spec, dict) or not spec:
        return "not-a-spec"
    if any(k in spec for k in _spec._RAW_DIAGRAM_KEYS):
        return "raw-markup"
    kind = spec.get("kind")
    if kind not in _spec.ALLOWED_KINDS:
        return "bad-kind"
    raw_nodes = spec.get("nodes")
    if not isinstance(raw_nodes, list):
        return "bad-shape"
    entry = _shape.message_entry if kind == "sequence" else _shape.edge_entry
    clean = _spec._sanitize_label
    try:
        nodes, node_labels = _shape.sanitize_nodes(raw_nodes[:_spec.MAX_NODES], clean)
        links, given = _shape.sanitize_links(spec.get(_links_key(kind)), set(nodes),
                                             clean, _spec.MAX_EDGES, entry=entry)
        _shape.sanitize_labels(spec.get("labels"), node_labels, clean)
    except _shape.ShapeError:
        return "bad-shape"
    if given and not links:
        return "all-edges-dropped"
    if _shape.is_degenerate(kind, nodes, given, links):
        return "no-edges"
    return "bad-shape"


def _texts(clean: dict) -> list:
    """Every string a reader sees: nodes, label keys and values, message labels."""
    labels = clean["labels"]
    texts = list(clean["nodes"]) + list(labels) + list(labels.values())
    if clean["kind"] == "sequence":
        texts += [m[2] for m in clean["messages"] if len(m) > 2]
    return texts


def _why_unconnected(clean: dict) -> Optional[str]:
    """Check a sanitized spec: dict labels, node count, orphan nodes, edge count."""
    if any(m in str(t) for t in _texts(clean) for m in _DICT_MARKERS):
        return "dict-label"
    kind = clean["kind"]
    nodes = set(clean["nodes"])
    if kind in _PAIR_KINDS and len(nodes) < 2:
        return "too-few-nodes"
    links = clean[_links_key(kind)]
    if not links:
        # A decision draws as a hub; a lone before-after node has nothing to join.
        return "no-edges" if kind != "decision" and len(nodes) > 1 else None
    touched = {end for link in links for end in link[:2]}
    return "orphan-node" if nodes - touched else None


def problem(spec) -> Optional[str]:
    """A REASONS slug naming why the diagram is unusable or unconnected, else None."""
    clean = _spec.sanitize_spec(spec)
    if clean is None:
        return _why_unusable(spec)
    return _why_unconnected(clean)
