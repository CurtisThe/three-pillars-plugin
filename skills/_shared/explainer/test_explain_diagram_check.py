"""test_explain_diagram_check.py — deterministic diagram check with reasons."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from explain_diagram_check import REASONS, problem, reason_text

DICT_REPR = "{'id': 'a', 'label': 'x'}"


def _flow(nodes=("a", "b", "c"), edges=(("a", "b"), ("b", "c")), **extra):
    return {"kind": "flow", "nodes": list(nodes),
            "edges": [list(e) for e in edges], **extra}


def test_connected_flow_passes():
    assert problem(_flow()) is None


def test_connected_flow_with_dict_items_passes():
    spec = {"kind": "flow",
            "nodes": [{"id": "a", "label": "Alpha"}, {"id": "b"}],
            "edges": [{"from": "a", "to": "b"}]}
    assert problem(spec) is None


def test_connected_sequence_passes():
    spec = {"kind": "sequence", "nodes": ["u", "s"],
            "messages": [["u", "s", "hi"], ["s", "u", "ok"]]}
    assert problem(spec) is None


def test_decision_with_no_edges_is_a_hub():
    assert problem({"kind": "decision", "nodes": ["q", "yes", "no"]}) is None


def test_one_node_before_after_passes():
    assert problem({"kind": "before-after", "nodes": ["a"]}) is None


@pytest.mark.parametrize("marker", [
    "{'id': 'a'}", "x 'id': 'a'", '{"id": "a"}', 'x "id": "a"', DICT_REPR,
])
def test_dict_repr_in_node_label(marker):
    assert problem(_flow(nodes=[marker, "b"], edges=[[marker, "b"]])) == "dict-label"


def test_dict_repr_in_labels_value():
    assert problem(_flow(labels={"a": DICT_REPR})) == "dict-label"


def test_dict_repr_in_labels_key():
    assert problem(_flow(labels={DICT_REPR: "fine"})) == "dict-label"


def test_dict_repr_in_message_label():
    spec = {"kind": "sequence", "nodes": ["u", "s"],
            "messages": [["u", "s", DICT_REPR]]}
    assert problem(spec) == "dict-label"


@pytest.mark.parametrize("spec", [None, [], ["flow"], 42, {}])
def test_not_a_spec(spec):
    assert problem(spec) == "not-a-spec"


@pytest.mark.parametrize("spec", [
    "<svg></svg>", "graph TD; a-->b",
    {"svg": "<svg></svg>"}, {"mermaid": "graph TD"}, {"html": "<p>x</p>"},
    {"kind": "flow", "nodes": ["a", "b"], "edges": [["a", "b"]], "svg": "<svg/>"},
])
def test_raw_markup(spec):
    assert problem(spec) == "raw-markup"


@pytest.mark.parametrize("spec", [
    {"kind": "pie", "nodes": ["a"]}, {"nodes": ["a", "b"]}, {"kind": 3},
])
def test_bad_kind(spec):
    assert problem(spec) == "bad-kind"


@pytest.mark.parametrize("spec", [
    {"kind": "flow", "nodes": "ab"},
    {"kind": "flow"},
    {"kind": "flow", "nodes": [{"id": ["a"]}, "b"], "edges": [["b", "b"]]},
    {"kind": "flow", "nodes": [["a"], "b"], "edges": [["b", "b"]]},
    {"kind": "flow", "nodes": ["a", "b"], "edges": [[["a"], "b"]]},
    {"kind": "flow", "nodes": ["a", "b"], "edges": [["a", "b"]], "labels": {"a": ["x"]}},
    {"kind": "sequence", "nodes": ["u", "s"], "messages": [["u", "s", {"x": 1}]]},
])
def test_bad_shape(spec):
    assert problem(spec) == "bad-shape"


@pytest.mark.parametrize("spec", [
    _flow(edges=[["a", "zzz"], ["q", "b"]]),
    _flow(edges=[["a"]]),
    {"kind": "state", "nodes": ["a", "b"], "edges": [["x", "y"]]},
    {"kind": "sequence", "nodes": ["u", "s"], "messages": [["u", "nobody", "hi"]]},
    {"kind": "decision", "nodes": ["q", "yes"], "edges": [["q", "gone"]]},
])
def test_all_edges_dropped(spec):
    assert problem(spec) == "all-edges-dropped"


@pytest.mark.parametrize("spec", [
    {"kind": "flow", "nodes": ["a", "b", "c"]},
    {"kind": "flow", "nodes": ["a", "b"], "edges": []},
    {"kind": "state", "nodes": ["a", "b"], "edges": "a->b"},
    {"kind": "before-after", "nodes": ["a", "b"]},
    {"kind": "sequence", "nodes": ["u", "s"]},
    {"kind": "sequence", "nodes": ["u", "s"], "messages": []},
])
def test_no_edges(spec):
    assert problem(spec) == "no-edges"


@pytest.mark.parametrize("nodes", [["a"], []])
def test_flow_too_few_nodes(nodes):
    assert problem({"kind": "flow", "nodes": nodes, "edges": []}) == "too-few-nodes"


def test_flow_single_node_self_edge_is_too_few():
    spec = {"kind": "flow", "nodes": ["a"], "edges": [["a", "a"]]}
    assert problem(spec) == "too-few-nodes"


def test_flow_orphan_node():
    assert problem(_flow(nodes=["a", "b", "c"], edges=[["a", "b"]])) == "orphan-node"


def test_state_orphan_node():
    spec = {"kind": "state", "nodes": ["a", "b", "c"], "edges": [["a", "b"]]}
    assert problem(spec) == "orphan-node"


def test_before_after_orphan_node():
    spec = {"kind": "before-after", "nodes": ["a", "b", "c"], "edges": [["a", "b"]]}
    assert problem(spec) == "orphan-node"


def test_decision_with_edges_and_an_orphan():
    spec = {"kind": "decision", "nodes": ["q", "yes", "no"], "edges": [["q", "yes"]]}
    assert problem(spec) == "orphan-node"


def test_decision_with_all_nodes_touched_passes():
    spec = {"kind": "decision", "nodes": ["q", "yes", "no"],
            "edges": [["q", "yes"], ["q", "no"]]}
    assert problem(spec) is None


def test_sequence_participant_without_message():
    spec = {"kind": "sequence", "nodes": ["u", "s", "db"],
            "messages": [["u", "s", "hi"]]}
    assert problem(spec) == "orphan-node"


def test_problem_does_not_mutate_the_spec():
    spec = _flow(nodes=["a", "b", "c"], edges=[["a", "b"]])
    before = repr(spec)
    problem(spec)
    assert repr(spec) == before


def test_reasons_have_a_sentence_per_slug():
    assert set(REASONS) >= {
        "not-a-spec", "raw-markup", "bad-kind", "bad-shape", "all-edges-dropped",
        "no-edges", "too-few-nodes", "orphan-node", "dict-label",
    }
    for slug, sentence in REASONS.items():
        assert isinstance(sentence, str) and sentence.strip(), slug


def test_reason_text_returns_the_sentence():
    for slug, sentence in REASONS.items():
        assert reason_text(slug) == sentence


def test_reason_text_unknown_slug_still_gives_a_sentence():
    assert reason_text("no-such-slug").strip()


@pytest.mark.parametrize("spec", [
    None, "x", {"kind": "pie"}, {"kind": "flow", "nodes": "ab"},
    _flow(edges=[["a", "zzz"]]), {"kind": "flow", "nodes": ["a", "b"]},
    {"kind": "flow", "nodes": ["a"]}, _flow(nodes=["a", "b", "c"], edges=[["a", "b"]]),
    _flow(labels={"a": DICT_REPR}),
])
def test_every_problem_slug_is_a_known_reason(spec):
    assert problem(spec) in REASONS
