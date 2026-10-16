"""test_explain_spec_shape.py — node, edge and message item shape helpers."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from explain_spec_shape import ShapeError, edge_entry, message_entry, node_entry


def test_node_scalar_forms():
    assert node_entry("a") == ("a", None)
    assert node_entry(3) == (3, None)


def test_node_dict_forms():
    assert node_entry({"id": "a", "label": "Alpha"}) == ("a", "Alpha")
    assert node_entry({"id": "a", "extra": 1}) == ("a", None)


@pytest.mark.parametrize("bad", [
    {"id": 3}, {"label": "x"}, {"id": "a", "label": 4},
    {"id": ["a"]}, ["a"], {"id": {"x": 1}}, {"id": "a", "label": {"x": 1}},
])
def test_node_bad_raises(bad):
    with pytest.raises(ShapeError):
        node_entry(bad)


def test_edge_forms():
    assert edge_entry(["a", "b"]) == ("a", "b")
    assert edge_entry({"from": "a", "to": "b"}) == ("a", "b")
    assert edge_entry({"source": "a", "target": "b"}) == ("a", "b")


@pytest.mark.parametrize("item", [["a"], "ab", {"x": 1}, {"from": "a"}, 5])
def test_edge_none(item):
    assert edge_entry(item) is None


@pytest.mark.parametrize("bad", [
    [["a"], "b"], ["a", {"x": 1}], {"from": ["a"], "to": "b"},
    {"source": "a", "target": {"k": 1}},
])
def test_edge_container_raises(bad):
    with pytest.raises(ShapeError):
        edge_entry(bad)


def test_message_forms():
    assert message_entry(["a", "b", "hi"]) == ("a", "b", "hi")
    assert message_entry({"from": "a", "to": "b", "label": "hi"}) == ("a", "b", "hi")
    assert message_entry(
        {"source": "a", "target": "b", "label": "hi"}) == ("a", "b", "hi")


@pytest.mark.parametrize("item", [["a", "b"], "abc", {"label": "x"}, 5])
def test_message_none(item):
    assert message_entry(item) is None


@pytest.mark.parametrize("bad", [
    ["a", "b", ["x"]], [["a"], "b", "x"],
    {"from": "a", "to": "b", "label": {"k": 1}},
    {"from": {"k": 1}, "to": "b", "label": "x"},
])
def test_message_container_raises(bad):
    with pytest.raises(ShapeError):
        message_entry(bad)
