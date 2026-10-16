"""test_explain_spec_shapes.py — sanitize_spec on node/edge shapes and degenerate specs.

Covers the non-ext kinds (flow, state, decision):
  (a) {id, label} node dicts and {from, to} / {source, target} edge dicts
      sanitize to ids, labels and real edges; explicit labels win.
  (b) a container as a node id, an edge endpoint or a label, or a non-string
      node-dict id, makes the spec unusable (None), never str(dict).
  (c) degenerate specs (every given edge dropped, or a multi-node flow/state
      with no edge) give None; a decision with no edges and a one-node flow
      are kept.
  (d) plain-string specs sanitize as before.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from explain_spec import sanitize_spec  # noqa: E402

_RIPLEY_NODES = [
    {"id": "browser", "label": "Browser: home screen"},
    {"id": "api", "label": "API"},
]


def _spec(kind="flow", nodes=None, edges=None, labels=None):
    spec = {"kind": kind, "nodes": nodes if nodes is not None else ["a", "b"]}
    if edges is not None:
        spec["edges"] = edges
    if labels is not None:
        spec["labels"] = labels
    return spec


# ---------------------------------------------------------------------------
# (a) dict node and edge shapes
# ---------------------------------------------------------------------------

def test_ripley_from_to_flow_sanitizes():
    result = sanitize_spec(_spec(nodes=_RIPLEY_NODES,
                                 edges=[{"from": "browser", "to": "api"}]))
    assert result is not None
    assert result["kind"] == "flow"
    assert result["nodes"] == ["browser", "api"]
    assert result["edges"] == [["browser", "api"]]
    assert result["labels"] == {"browser": "Browser: home screen", "api": "API"}


def test_source_target_edge_dict_sanitizes():
    result = sanitize_spec(_spec(nodes=_RIPLEY_NODES,
                                 edges=[{"source": "browser", "target": "api"}]))
    assert result is not None
    assert result["edges"] == [["browser", "api"]]


@pytest.mark.parametrize("kind", ["flow", "state", "decision"])
def test_dict_shapes_work_for_every_core_kind(kind):
    result = sanitize_spec(_spec(kind=kind, nodes=_RIPLEY_NODES,
                                 edges=[{"from": "browser", "to": "api"}]))
    assert result is not None
    assert result["nodes"] == ["browser", "api"]
    assert result["edges"] == [["browser", "api"]]


def test_explicit_labels_entry_wins_over_node_dict_label():
    result = sanitize_spec(_spec(nodes=_RIPLEY_NODES,
                                 edges=[["browser", "api"]],
                                 labels={"browser": "Web client"}))
    assert result is not None
    assert result["labels"]["browser"] == "Web client"
    assert result["labels"]["api"] == "API"


def test_node_dict_without_label_adds_no_label():
    result = sanitize_spec(_spec(nodes=[{"id": "a"}, "b"], edges=[["a", "b"]]))
    assert result is not None
    assert result["nodes"] == ["a", "b"]
    assert result["labels"] == {}


def test_node_dict_extra_keys_ignored():
    nodes = [{"id": "a", "label": "Alpha", "shape": "box"}, {"id": "b"}]
    result = sanitize_spec(_spec(nodes=nodes, edges=[["a", "b"]]))
    assert result is not None
    assert result["nodes"] == ["a", "b"]
    assert result["labels"] == {"a": "Alpha"}


def test_node_dict_label_is_sanitized():
    nodes = [{"id": "a", "label": "see http://evil.example"}, "b"]
    result = sanitize_spec(_spec(nodes=nodes, edges=[["a", "b"]]))
    assert result is not None
    assert "http:" not in result["labels"]["a"]
    assert "//" not in result["labels"]["a"]


# ---------------------------------------------------------------------------
# (b) containers and non-string ids make the spec unusable
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("spec", [
    _spec(nodes=[{"id": {"name": "browser"}}, "api"], edges=[["browser", "api"]]),
    _spec(nodes=[{"id": 7, "label": "Seven"}, "api"], edges=[["7", "api"]]),
    _spec(nodes=[{"label": "no id"}, "api"], edges=[["a", "api"]]),
    _spec(nodes=[["browser"], "api"], edges=[["browser", "api"]]),
    _spec(nodes=["browser", "api"],
          edges=[{"from": {"id": "browser"}, "to": "api"}]),
    _spec(nodes=["browser", "api"],
          edges=[{"source": "browser", "target": ["api"]}]),
    _spec(nodes=["browser", "api"], edges=[["browser", {"id": "api"}]]),
    _spec(nodes=[{"id": "browser", "label": {"text": "B"}}, "api"],
          edges=[["browser", "api"]]),
    _spec(nodes=["browser", "api"], edges=[["browser", "api"]],
          labels={"browser": {"text": "B"}}),
], ids=["nested-dict-id", "int-dict-id", "missing-id", "list-node",
        "dict-from", "list-target", "dict-list-endpoint", "dict-node-label",
        "dict-labels-value"])
def test_container_or_bad_id_gives_none(spec):
    assert sanitize_spec(spec) is None


@pytest.mark.parametrize("kind", ["flow", "state", "decision"])
def test_nested_dict_node_is_none_for_every_core_kind(kind):
    spec = _spec(kind=kind, nodes=[{"id": {"x": 1}}, "b"], edges=[["a", "b"]])
    assert sanitize_spec(spec) is None


# ---------------------------------------------------------------------------
# (c) degenerate specs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", ["flow", "state"])
@pytest.mark.parametrize("edges", [None, []], ids=["edges-absent", "edges-empty"])
def test_two_node_flow_or_state_without_edges_is_none(kind, edges):
    assert sanitize_spec(_spec(kind=kind, nodes=["a", "b"], edges=edges)) is None


@pytest.mark.parametrize("nodes", [["a"], ["a", "b"]], ids=["one-node", "two-node"])
def test_flow_whose_only_edge_names_unlisted_node_is_none(nodes):
    assert sanitize_spec(_spec(nodes=nodes, edges=[["a", "ghost"]])) is None


def test_ripley_shape_with_dangling_dict_edge_is_none():
    spec = _spec(nodes=_RIPLEY_NODES, edges=[{"from": "browser", "to": "db"}])
    assert sanitize_spec(spec) is None


@pytest.mark.parametrize("edges", [
    [["root", "yes"], ["root", "no"]],
    [{"from": "root", "to": "yes"}],
    [["yes"]],
], ids=["dangling-lists", "dangling-dict", "malformed"])
def test_decision_whose_given_edges_all_drop_is_none(edges):
    spec = _spec(kind="decision", nodes=["yes", "no"], edges=edges)
    assert sanitize_spec(spec) is None


@pytest.mark.parametrize("edges", [None, []], ids=["edges-absent", "edges-empty"])
def test_decision_with_two_nodes_and_no_edges_is_kept(edges):
    result = sanitize_spec(_spec(kind="decision", nodes=["yes", "no"], edges=edges))
    assert result is not None
    assert result["nodes"] == ["yes", "no"]
    assert result["edges"] == []


@pytest.mark.parametrize("edges", [None, []], ids=["edges-absent", "edges-empty"])
def test_one_node_flow_is_kept(edges):
    result = sanitize_spec(_spec(nodes=["a"], edges=edges, labels={"a": "Only"}))
    assert result is not None
    assert result["nodes"] == ["a"]
    assert result["edges"] == []
    assert result["labels"] == {"a": "Only"}


def test_some_dangling_edges_dropped_but_spec_kept():
    result = sanitize_spec(_spec(nodes=["a", "b"],
                                 edges=[["a", "b"], ["a", "c"], ["x", "b"]]))
    assert result is not None
    assert result["edges"] == [["a", "b"]]


# ---------------------------------------------------------------------------
# (d) plain-string specs unchanged
# ---------------------------------------------------------------------------

def test_plain_string_flow_sanitizes_as_before():
    spec = {
        "kind": "flow",
        "nodes": ["a", "b", "c"],
        "edges": [["a", "b"], ["b", "c"]],
        "labels": {"a": "Start", "b": "Middle", "c": "End"},
    }
    assert sanitize_spec(spec) == {
        "kind": "flow",
        "nodes": ["a", "b", "c"],
        "edges": [["a", "b"], ["b", "c"]],
        "labels": {"a": "Start", "b": "Middle", "c": "End"},
    }


def test_plain_state_and_decision_sanitize_as_before():
    state = {"kind": "state", "nodes": ["idle", "done"],
             "edges": [["idle", "done"]], "labels": {}}
    assert sanitize_spec(state) == state
    decision = {"kind": "decision", "nodes": ["root", "yes"],
                "edges": [["root", "yes"]], "labels": {"root": "Merge?"}}
    assert sanitize_spec(decision) == decision


def test_scalar_node_ids_coerced_to_str():
    result = sanitize_spec(_spec(nodes=[1, 2], edges=[[1, 2]]))
    assert result is not None
    assert result["nodes"] == ["1", "2"]
    assert result["edges"] == [["1", "2"]]


def test_tuple_edges_still_accepted():
    result = sanitize_spec(_spec(nodes=["a", "b"], edges=[("a", "b")]))
    assert result is not None
    assert result["edges"] == [["a", "b"]]


def test_labels_for_unlisted_keys_kept_as_before():
    result = sanitize_spec(_spec(nodes=["a", "b"], edges=[["a", "b"]],
                                 labels={"a": "A", "zz": "Extra"}))
    assert result is not None
    assert result["labels"] == {"a": "A", "zz": "Extra"}
