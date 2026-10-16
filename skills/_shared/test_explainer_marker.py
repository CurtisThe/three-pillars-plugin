"""Tests for explainer_marker (design explainer-agent, spec: detailed-design.md)."""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import explainer_marker as em  # noqa: E402


def test_prefix_constant():
    assert em.MARKER_PREFIX == "<!-- tp-explainer:"


def test_marker_round_trip():
    m = em.marker("pr-brief", "s1", "abc123")
    assert m == "<!-- tp-explainer:pr-brief slug=s1 head=abc123 -->"
    assert em.parse(m) == {"kind": "pr-brief", "slug": "s1", "head": "abc123"}


def test_parse_plain_is_none():
    assert em.parse("plain") is None


def test_parse_with_trailing_body():
    body = em.marker("rulings", "s2", "dead") + "\n\nhello"
    assert em.parse(body) == {"kind": "rulings", "slug": "s2", "head": "dead"}


def test_is_explainer_prefix_only():
    assert em.is_explainer(em.marker("pr-brief", "s", "h") + "\nbody")
    assert not em.is_explainer("quoted " + em.MARKER_PREFIX + "pr-brief slug=s head=h -->")
    assert not em.is_explainer("")


def test_drop_marked_dicts():
    keep = {"body": "please fix this"}
    drop = {"body": em.marker("pr-brief", "s", "h") + "\nbrief"}
    assert em.drop_marked([keep, drop]) == [keep]


def test_drop_marked_objects():
    keep = SimpleNamespace(body="reviewer says no")
    drop = SimpleNamespace(body=em.marker("rulings", "s", "h"))
    assert em.drop_marked([drop, keep]) == [keep]
