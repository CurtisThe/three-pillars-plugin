"""test_explain_spec_ext.py — the before-after and sequence diagram kinds.

Covers explainer-agent plan Task 2.1 (detailed-design: "explain_spec_ext
sanitizes the two new kinds (status per node; ordered [src, dst, label]
messages)"; design: "the model never writes raw SVG or mermaid"):
  - ALLOWED_KINDS grows by "before-after" and "sequence".
  - before-after: every kept node has a status from the closed enum; an
    unknown or missing status becomes "existing"; a status key that is not a
    node is dropped; dangling edges are dropped.
  - sequence: ordered [src, dst, label] messages; a message naming an unknown
    participant or shorter than 3 items is dropped; MAX_EDGES / MAX_NODES caps.
  - Labels are neutralized exactly as for the existing kinds.
  - A string spec, or a dict carrying an svg / mermaid / html key, is None.
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest  # noqa: E402

import explain_offline  # noqa: E402
from explain_spec import ALLOWED_KINDS, MAX_EDGES, MAX_NODES, sanitize_spec  # noqa: E402

_HOSTILE_LABELS = ("see https://x", "<svg onload=1>", "<svg>https://x")


def _before_after(**overrides):
    spec = {
        "kind": "before-after",
        "nodes": ["explain_spec", "explain_spec_ext", "explain_svg"],
        "edges": [["explain_spec", "explain_spec_ext"], ["explain_spec", "explain_svg"]],
        "status": {"explain_spec": "changed", "explain_spec_ext": "added",
                   "explain_svg": "existing"},
    }
    spec.update(overrides)
    return spec


def _sequence(**overrides):
    spec = {
        "kind": "sequence",
        "nodes": ["seat", "explainer", "forge"],
        "messages": [["seat", "explainer", "draft brief"],
                     ["explainer", "forge", "post comment"],
                     ["forge", "seat", "comment url"]],
    }
    spec.update(overrides)
    return spec


def _valid_spec(kind):
    if kind == "before-after":
        return _before_after()
    if kind == "sequence":
        return _sequence()
    return {"kind": kind, "nodes": ["a", "b"], "edges": [["a", "b"]]}


def _flow_label(text):
    """How the existing kinds sanitize the same label text."""
    return sanitize_spec({"kind": "flow", "nodes": ["a"], "edges": [],
                          "labels": {"a": text}})["labels"]["a"]


def test_allowed_kinds_add_before_after_and_sequence():
    assert ALLOWED_KINDS == ("flow", "decision", "state", "before-after", "sequence")


# ---------------------------------------------------------------------------
# before-after
# ---------------------------------------------------------------------------

class TestBeforeAfter:

    def test_output_shape(self):
        result = sanitize_spec(_before_after())
        assert result is not None
        assert set(result) == {"kind", "nodes", "edges", "labels", "status"}
        assert result["kind"] == "before-after"

    def test_all_four_statuses_are_kept(self):
        from explain_spec_ext import STATUSES
        nodes = ["explain_spec", "explain_spec_ext", "explain_svg", "explain_mermaid"]
        status = dict(zip(nodes, STATUSES))
        edges = [[a, b] for a, b in zip(nodes, nodes[1:])]
        result = sanitize_spec(_before_after(nodes=nodes, edges=edges, status=status))
        assert result["status"] == status

    def test_every_kept_node_has_a_status_from_the_closed_enum(self):
        from explain_spec_ext import STATUSES
        result = sanitize_spec(_before_after())
        assert set(result["status"]) == set(result["nodes"])
        assert set(result["status"].values()) <= set(STATUSES)

    def test_unknown_status_becomes_existing(self):
        result = sanitize_spec(_before_after(status={"explain_spec": "deleted",
                                                     "explain_svg": None}))
        assert result["status"]["explain_spec"] == "existing"
        assert result["status"]["explain_svg"] == "existing"

    def test_missing_status_becomes_existing(self):
        result = sanitize_spec(_before_after(status={"explain_spec_ext": "added"}))
        assert result["status"] == {"explain_spec": "existing",
                                    "explain_spec_ext": "added",
                                    "explain_svg": "existing"}

    def test_absent_status_map_makes_every_node_existing(self):
        spec = _before_after()
        del spec["status"]
        result = sanitize_spec(spec)
        assert result is not None
        assert set(result["status"].values()) == {"existing"}
        assert set(result["status"]) == set(result["nodes"])

    def test_status_key_that_is_not_a_node_is_dropped(self):
        result = sanitize_spec(_before_after(status={"explain_spec": "changed",
                                                     "ghost": "added"}))
        assert "ghost" not in result["status"]
        assert result["status"]["explain_spec"] == "changed"

    def test_edge_to_unknown_node_is_dropped(self):
        result = sanitize_spec(_before_after(edges=[["explain_spec", "explain_svg"],
                                                    ["explain_spec", "ghost"],
                                                    ["ghost", "explain_svg"]]))
        assert result["edges"] == [["explain_spec", "explain_svg"]]

    def test_nodes_and_edges_are_capped(self):
        nodes = [f"n{i}" for i in range(MAX_NODES + 5)]
        edges = [[nodes[0], nodes[1]]] * (MAX_EDGES + 5)
        result = sanitize_spec(_before_after(nodes=nodes, edges=edges, status={}))
        assert len(result["nodes"]) == MAX_NODES
        assert len(result["edges"]) == MAX_EDGES
        assert set(result["status"]) == set(result["nodes"])

    @pytest.mark.parametrize("text", _HOSTILE_LABELS)
    def test_label_is_neutralized_as_for_existing_kinds(self, text):
        result = sanitize_spec(_before_after(labels={"explain_spec": text}))
        label = result["labels"]["explain_spec"]
        assert label == _flow_label(text)
        assert "https:" not in label and "<svg" not in label
        explain_offline.assert_offline(f"<span>{label}</span>")


# ---------------------------------------------------------------------------
# sequence
# ---------------------------------------------------------------------------

class TestSequence:

    def test_output_shape(self):
        result = sanitize_spec(_sequence())
        assert result is not None
        assert set(result) == {"kind", "nodes", "messages", "labels"}
        assert result["kind"] == "sequence"

    def test_message_order_is_kept(self):
        result = sanitize_spec(_sequence())
        assert [list(m) for m in result["messages"]] == [
            ["seat", "explainer", "draft brief"],
            ["explainer", "forge", "post comment"],
            ["forge", "seat", "comment url"],
        ]

    def test_message_naming_unknown_participant_is_dropped(self):
        result = sanitize_spec(_sequence(messages=[["seat", "ghost", "lost"],
                                                   ["seat", "explainer", "draft brief"],
                                                   ["ghost", "forge", "lost"]]))
        assert [list(m) for m in result["messages"]] == [
            ["seat", "explainer", "draft brief"]]

    def test_message_shorter_than_three_items_is_dropped(self):
        result = sanitize_spec(_sequence(messages=[["seat", "explainer"],
                                                   ["explainer", "forge", "post comment"]]))
        assert [list(m) for m in result["messages"]] == [
            ["explainer", "forge", "post comment"]]

    def test_messages_capped_at_max_edges_in_order(self):
        messages = [["seat", "explainer", f"m{i}"] for i in range(MAX_EDGES + 5)]
        result = sanitize_spec(_sequence(messages=messages))
        assert [m[2] for m in result["messages"]] == [f"m{i}" for i in range(MAX_EDGES)]

    def test_nodes_capped_at_max_nodes(self):
        nodes = [f"p{i}" for i in range(MAX_NODES + 5)]
        result = sanitize_spec(_sequence(nodes=nodes, messages=[["p0", "p1", "call"]]))
        assert len(result["nodes"]) == MAX_NODES

    @pytest.mark.parametrize("text", _HOSTILE_LABELS)
    def test_message_label_is_neutralized_as_for_existing_kinds(self, text):
        result = sanitize_spec(_sequence(messages=[["seat", "explainer", text]]))
        label = result["messages"][0][2]
        assert label == _flow_label(text)
        assert "https:" not in label and "<svg" not in label
        explain_offline.assert_offline(f"<span>{label}</span>")

    @pytest.mark.parametrize("text", _HOSTILE_LABELS)
    def test_labels_map_is_neutralized_as_for_existing_kinds(self, text):
        result = sanitize_spec(_sequence(labels={"seat": text}))
        assert result["labels"]["seat"] == _flow_label(text)


# ---------------------------------------------------------------------------
# raw diagrams are rejected
# ---------------------------------------------------------------------------

def test_string_spec_is_rejected():
    assert sanitize_spec("flowchart LR; a-->b") is None


@pytest.mark.parametrize("raw_key", ("svg", "mermaid", "html"))
@pytest.mark.parametrize("kind", ALLOWED_KINDS)
def test_dict_with_raw_markup_key_is_rejected_for_every_kind(kind, raw_key):
    spec = _valid_spec(kind)
    assert sanitize_spec(spec) is not None
    spec[raw_key] = "flowchart LR; a-->b"
    assert sanitize_spec(spec) is None
