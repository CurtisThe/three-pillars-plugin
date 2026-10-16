"""test_explain_spec_ext_shapes.py — before-after and sequence take the item shapes.

Covers explainer-diagram-fidelity plan Task 1.3 (design Parts 1 and 2):
  - before-after accepts {id, label} node dicts and {from, to} edge dicts;
    node labels join labels, the status map still keys on node ids.
  - sequence accepts {id, label} participants and {from, to, label} message
    dicts, keeping message order.
  - A container participant id or message endpoint makes the spec None.
  - Degenerate specs are None: a multi-node before-after with no edge, a
    multi-participant sequence with no message or whose messages all drop.
  - A one-node before-after is kept.

Tests assert on the sanitized dict sanitize_ext returns (its public shape),
not on internals (skills/_shared/test-fragility.md).
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from explain_spec import sanitize_spec  # noqa: E402
from explain_spec_ext import sanitize_ext  # noqa: E402


def _ba(**overrides):
    spec = {
        "kind": "before-after",
        "nodes": [{"id": "a", "label": "Alpha"}, {"id": "b", "label": "Beta"}],
        "edges": [{"from": "a", "to": "b"}],
        "status": {"a": "changed", "b": "added"},
    }
    spec.update(overrides)
    return spec


def _seq(**overrides):
    spec = {
        "kind": "sequence",
        "nodes": [{"id": "client", "label": "Client"}, {"id": "server"}],
        "messages": [{"from": "client", "to": "server", "label": "request"},
                     {"from": "server", "to": "client", "label": "reply"}],
    }
    spec.update(overrides)
    return spec


class TestBeforeAfterShapes:
    def test_dict_nodes_and_edges_are_kept(self):
        result = sanitize_ext(_ba())
        assert result["nodes"] == ["a", "b"]
        assert result["edges"] == [["a", "b"]]
        assert result["labels"] == {"a": "Alpha", "b": "Beta"}
        assert result["status"] == {"a": "changed", "b": "added"}

    def test_source_target_edge_dict_is_kept(self):
        result = sanitize_ext(_ba(edges=[{"source": "b", "target": "a"}]))
        assert result["edges"] == [["b", "a"]]

    def test_spec_labels_win_over_node_dict_label(self):
        result = sanitize_ext(_ba(labels={"a": "Own"}))
        assert result["labels"] == {"a": "Own", "b": "Beta"}

    def test_through_sanitize_spec(self):
        result = sanitize_spec(_ba())
        assert result["edges"] == [["a", "b"]]
        assert result["labels"]["a"] == "Alpha"

    def test_container_node_id_is_none(self):
        assert sanitize_ext(_ba(nodes=[{"id": {"x": 1}}, "b"])) is None

    def test_container_edge_endpoint_is_none(self):
        assert sanitize_ext(_ba(edges=[{"from": ["a"], "to": "b"}])) is None

    def test_two_nodes_no_edge_is_none(self):
        assert sanitize_ext(_ba(edges=[])) is None

    def test_all_edges_dropped_is_none(self):
        assert sanitize_ext(_ba(edges=[["a", "zz"]])) is None

    def test_one_node_is_kept(self):
        result = sanitize_ext(_ba(nodes=[{"id": "a", "label": "Alpha"}], edges=[],
                                  status={"a": "removed"}))
        assert result["nodes"] == ["a"]
        assert result["edges"] == []
        assert result["status"] == {"a": "removed"}


class TestSequenceShapes:
    def test_dict_messages_keep_order(self):
        result = sanitize_ext(_seq())
        assert result["nodes"] == ["client", "server"]
        assert result["messages"] == [["client", "server", "request"],
                                      ["server", "client", "reply"]]
        assert result["labels"] == {"client": "Client"}

    def test_list_messages_still_work(self):
        result = sanitize_ext(_seq(messages=[["client", "server", "go"]]))
        assert result["messages"] == [["client", "server", "go"]]

    def test_through_sanitize_spec(self):
        result = sanitize_spec(_seq())
        assert [m[2] for m in result["messages"]] == ["request", "reply"]

    def test_container_participant_id_is_none(self):
        assert sanitize_ext(_seq(nodes=[["client"], "server"])) is None

    def test_container_message_endpoint_is_none(self):
        bad = [{"from": {"id": "client"}, "to": "server", "label": "x"}]
        assert sanitize_ext(_seq(messages=bad)) is None

    def test_two_participants_no_message_is_none(self):
        assert sanitize_ext(_seq(messages=[])) is None

    def test_missing_messages_is_none(self):
        spec = _seq()
        del spec["messages"]
        assert sanitize_ext(spec) is None

    def test_all_messages_dropped_is_none(self):
        bad = [{"from": "client", "to": "ghost", "label": "x"}, ["client", "server"]]
        assert sanitize_ext(_seq(messages=bad)) is None
