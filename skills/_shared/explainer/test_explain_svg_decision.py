"""test_explain_svg_decision.py — decision SVG draws real edges first (task 1.8)."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import explain_offline
from explain_svg import spec_svg


def _connectors(svg: str) -> int:
    return svg.count("<line") + svg.count("<path")


def test_chain_draws_only_given_edges():
    svg = spec_svg({"kind": "decision", "nodes": ["a", "b", "c"],
                    "edges": [["a", "b"], ["b", "c"]]})
    assert _connectors(svg) == 2
    # b->c is an arc between branch boxes; no root-to-c straight line.
    assert svg.count("<path") == 1
    assert svg.count("<line") == 1


def test_no_edges_draws_one_connector_per_branch():
    svg = spec_svg({"kind": "decision", "nodes": ["a", "b", "c", "d"],
                    "edges": []})
    assert _connectors(svg) == 3


def test_dict_nodes_have_no_dict_text_and_are_offline():
    svg = spec_svg({"kind": "decision",
                    "nodes": [{"id": "a", "label": "Root"},
                              {"id": "b", "label": "Bee"},
                              {"id": "c", "label": "Sea"}],
                    "edges": [["a", "b"], ["b", "c"]]})
    assert "{'id'" not in svg and "'label'" not in svg
    explain_offline.assert_offline(svg)
