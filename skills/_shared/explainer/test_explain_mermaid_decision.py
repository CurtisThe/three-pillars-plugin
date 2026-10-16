"""Tests for the mermaid `decision` body: real edges first, hub as fallback.

A decision with edges draws exactly those edges; with none it draws the hub
fan-out (first node to every other). {id,label} nodes show their labels.
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE.parent, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from explain_mermaid import spec_mermaid  # noqa: E402


def _lines(spec) -> set:
    return {ln.strip() for ln in spec_mermaid(spec).splitlines()}


def test_edges_drawn_without_hub_fanout():
    lines = _lines({"kind": "decision", "nodes": ["a", "b", "c"],
                    "edges": [["a", "b"], ["b", "c"]]})
    assert "n0 --> n1" in lines
    assert "n1 --> n2" in lines
    assert "n0 --> n2" not in lines


def test_no_edges_draws_hub():
    lines = _lines({"kind": "decision", "nodes": ["a", "b", "c"]})
    assert "n0 --> n1" in lines
    assert "n0 --> n2" in lines


def test_id_label_nodes_show_labels_not_dicts():
    text = spec_mermaid({"kind": "decision",
                         "nodes": [{"id": "a", "label": "Alpha"},
                                   {"id": "b", "label": "Beta"}]})
    assert '"Alpha"' in text and '"Beta"' in text
    assert "{" not in text and "'id'" not in text
