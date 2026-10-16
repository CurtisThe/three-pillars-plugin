"""explainer/explain_spec_shape.py — shape helpers for spec node/edge/message items.

Public API:
    ShapeError                   ValueError: the item has an unusable shape
    LINKED_KINDS                 kinds that need a link once they have 2+ nodes
    node_entry(item)             -> (id, label_or_None)
    edge_entry(item)             -> (src, dst) or None
    message_entry(item)          -> (src, dst, label) or None
    sanitize_nodes(raw, sanitize_label)              -> (ids, node_labels)
    sanitize_links(raw, node_set, sanitize_label, cap, entry=edge_entry)
                                 -> (kept_links, given_count)
    sanitize_labels(raw, node_labels, sanitize_label) -> labels
    is_degenerate(kind, nodes, given, kept)          -> bool

Node item: a scalar, or {"id": str, "label": str (optional)}; extra keys are
ignored. Edge item: [src, dst], {"from", "to"} or {"source", "target"}.
Message item: [src, dst, label] or the same dicts plus "label".

A container (dict or list) as a node id, endpoint or label, a missing or
non-string dict id, or a non-string dict label raises ShapeError. A merely
malformed edge or message (too short, no key pair) returns None so the caller
drops it. The *_entry helpers return raw values; the sanitize_* helpers run
every id, endpoint and label through the caller's label sanitizer and raise
ShapeError like the entries do. A spec is degenerate when links were given
and every one was dropped, or a LINKED_KINDS spec has 2+ nodes and no link;
a decision with no edges is not (the renderer's hub fan-out draws it).

Stdlib only. Flat-import package — no __init__.py.
"""
from __future__ import annotations

from typing import Any, Callable, Optional, Tuple

_PAIRS = (("from", "to"), ("source", "target"))
LINKED_KINDS = ("flow", "state", "before-after", "sequence")


class ShapeError(ValueError):
    """An item has a shape the sanitizer must not coerce."""


def _scalar(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        raise ShapeError("container where a scalar was expected")
    return value


def node_entry(item: Any) -> Tuple[Any, Optional[str]]:
    if isinstance(item, dict):
        if "id" not in item or not isinstance(item["id"], str):
            raise ShapeError("node dict needs a string id")
        label = item.get("label")
        if label is not None and not isinstance(label, str):
            raise ShapeError("node label must be a string")
        return item["id"], label
    return _scalar(item), None


def _ends(item: dict) -> Optional[Tuple[Any, Any]]:
    for a, b in _PAIRS:
        if a in item and b in item:
            return _scalar(item[a]), _scalar(item[b])
    return None


def edge_entry(item: Any) -> Optional[Tuple[Any, Any]]:
    if isinstance(item, dict):
        return _ends(item)
    if isinstance(item, list) and len(item) >= 2:
        return _scalar(item[0]), _scalar(item[1])
    return None


def message_entry(item: Any) -> Optional[Tuple[Any, Any, Any]]:
    if isinstance(item, dict):
        ends = _ends(item)
        if ends is None:
            return None
        return ends[0], ends[1], _scalar(item.get("label", ""))
    if isinstance(item, list) and len(item) >= 3:
        return _scalar(item[0]), _scalar(item[1]), _scalar(item[2])
    return None


def sanitize_nodes(raw: list, sanitize_label: Callable) -> Tuple[list, dict]:
    """Sanitized node ids, plus {id: label} for node dicts that carry one."""
    nodes, labels = [], {}
    for item in raw:
        node_id, label = node_entry(item)
        node_id = sanitize_label(node_id)
        nodes.append(node_id)
        if label:
            labels.setdefault(node_id, sanitize_label(label))
    return nodes, labels


def sanitize_links(raw: Any, node_set: set, sanitize_label: Callable, cap: int,
                   entry: Callable = edge_entry) -> Tuple[list, int]:
    """Links (edges, or messages with entry=message_entry) between known nodes.

    Returns (kept, given): kept is a list of sanitized part lists whose first
    two parts name nodes in node_set; given counts the items read after the
    cap. A non-list raw gives nothing; a tuple item is read as a list.
    """
    items = raw[:cap] if isinstance(raw, list) else []
    kept = []
    for item in items:
        parts = entry(list(item) if isinstance(item, tuple) else item)
        if parts is None:
            continue
        parts = [sanitize_label(p) for p in parts]
        if parts[0] in node_set and parts[1] in node_set:
            kept.append(parts)
    return kept, len(items)


def sanitize_labels(raw: Any, node_labels: dict, sanitize_label: Callable) -> dict:
    """The spec's own labels dict, then node-dict labels for nodes it omits."""
    labels = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            labels[sanitize_label(_scalar(key))] = sanitize_label(_scalar(value))
    for node_id, label in node_labels.items():
        labels.setdefault(node_id, label)
    return labels


def is_degenerate(kind: Any, nodes: list, given: int, kept: list) -> bool:
    """True when every given link dropped, or a linked kind has 2+ nodes and no link."""
    if given and not kept:
        return True
    return kind in LINKED_KINDS and len(set(nodes)) > 1 and not kept
