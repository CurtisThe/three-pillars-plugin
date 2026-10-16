"""test_explain_svg_ext.py — offline SVG for the before-after and sequence kinds.

Covers explainer-agent plan Task 2.2 (detailed-design: "explain_svg_ext:
before/after SVG (fill by added/changed/removed/existing) and sequence SVG";
design: "One spec renders to offline SVG and to mermaid; the model never
writes raw SVG or mermaid"):
  - STATUS_FILL has exactly the four STATUSES keys, with four distinct fills.
  - A before-after spec with one node of each status draws all four fills,
    and a node's fill follows its status.
  - A sequence spec of three messages draws the three messages top to bottom
    in message order.
  - A hostile label is escaped exactly once.
  - Every output passes explain_offline.assert_offline.
  - An unusable spec gives the existing empty SVG (spec_svg(None)).

Assertions read the parsed SVG structure (ElementTree), never pinned markup.
"""
import html
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest  # noqa: E402

import explain_offline  # noqa: E402
import explain_spec  # noqa: E402
import explain_svg_ext  # noqa: E402
from explain_spec_ext import STATUSES  # noqa: E402
from explain_svg import spec_svg  # noqa: E402

_SCRIPT_LABEL = "<script>alert(1)</script>"
_MESSAGE_LABELS = ("draft brief", "post comment", "comment url")


def _before_after(**overrides):
    # The design's own change: primitives move from pro into core.
    spec = {
        "kind": "before-after",
        "nodes": ["explain_spec", "explain_spec_ext", "explain_svg", "pro_copy"],
        "edges": [["explain_spec", "explain_spec_ext"],
                  ["explain_svg", "explain_spec"]],
        "labels": {"pro_copy": "pro diagram copy"},
        "status": {"explain_spec": "changed", "explain_spec_ext": "added",
                   "explain_svg": "existing", "pro_copy": "removed"},
    }
    spec.update(overrides)
    return spec


def _sequence(**overrides):
    spec = {
        "kind": "sequence",
        "nodes": ["seat", "explainer", "forge"],
        "messages": [["seat", "explainer", _MESSAGE_LABELS[0]],
                     ["explainer", "forge", _MESSAGE_LABELS[1]],
                     ["forge", "seat", _MESSAGE_LABELS[2]]],
    }
    spec.update(overrides)
    return spec


def _parse(svg: str):
    return ET.fromstring(svg)  # nosec B314 — SVG this test just rendered


def _render(spec) -> str:
    """spec_svg output, checked offline and well-formed (parses as XML)."""
    svg = spec_svg(spec)
    explain_offline.assert_offline(svg)
    _parse(svg)
    return svg


def _status_fills_used(svg: str) -> set:
    """The STATUS_FILL values that appear as a fill on any SVG element."""
    status_fills = set(explain_svg_ext.STATUS_FILL.values())
    return {el.get("fill") for el in _parse(svg).iter()} & status_fills


def _texts_in_order(svg: str) -> list:
    """(text, y) for every <text> element, in document order."""
    return [("".join(el.itertext()), float(el.get("y")))
            for el in _parse(svg).iter()
            if el.tag.rsplit("}", 1)[-1] == "text"]


# ---------------------------------------------------------------------------
# before-after: fill by status
# ---------------------------------------------------------------------------

def test_status_fill_has_one_distinct_fill_per_status():
    assert set(explain_svg_ext.STATUS_FILL) == set(STATUSES)
    assert len(set(explain_svg_ext.STATUS_FILL.values())) == len(STATUSES)


def test_before_after_draws_one_fill_per_status():
    svg = _render(_before_after())
    assert _status_fills_used(svg) == set(explain_svg_ext.STATUS_FILL.values())


@pytest.mark.parametrize("status", STATUSES)
def test_before_after_node_fill_follows_its_status(status):
    """Metamorphic: moving a lone node's status moves its fill with it."""
    spec = _before_after(nodes=["explain_spec"], edges=[],
                         status={"explain_spec": status})
    svg = _render(spec)
    assert _status_fills_used(svg) == {explain_svg_ext.STATUS_FILL[status]}


def test_before_after_draws_node_labels():
    svg = _render(_before_after())
    texts = [t for t, _ in _texts_in_order(svg)]
    for shown in ("explain_spec", "explain_spec_ext", "explain_svg",
                  "pro diagram copy"):
        assert texts.count(shown) == 1


def test_before_after_entry_point_matches_spec_svg():
    spec = _before_after()
    sanitized = explain_spec.sanitize_spec(spec)
    assert explain_svg_ext.before_after_svg(sanitized) == spec_svg(spec)


# ---------------------------------------------------------------------------
# sequence: messages in order
# ---------------------------------------------------------------------------

def test_sequence_draws_three_messages_in_message_order():
    svg = _render(_sequence())
    texts = _texts_in_order(svg)
    shown = [(t, y) for t, y in texts if t in _MESSAGE_LABELS]
    assert [t for t, _ in shown] == list(_MESSAGE_LABELS)
    ys = [y for _, y in shown]
    assert ys == sorted(ys) and len(set(ys)) == len(ys), "top to bottom"


def test_sequence_draws_each_participant():
    svg = _render(_sequence())
    texts = [t for t, _ in _texts_in_order(svg)]
    for participant in ("seat", "explainer", "forge"):
        assert texts.count(participant) == 1


def test_sequence_entry_point_matches_spec_svg():
    spec = _sequence()
    sanitized = explain_spec.sanitize_spec(spec)
    assert explain_svg_ext.sequence_svg(sanitized) == spec_svg(spec)


# ---------------------------------------------------------------------------
# hostile labels: escaped exactly once, offline
# ---------------------------------------------------------------------------

def _hostile_specs(label: str) -> dict:
    return {
        "before-after": _before_after(labels={"explain_spec": label}),
        "sequence": _sequence(messages=[["seat", "explainer", label]]),
    }


def _sanitized_label(kind: str, sanitized: dict) -> str:
    if kind == "sequence":
        return sanitized["messages"][0][2]
    return sanitized["labels"]["explain_spec"]


@pytest.mark.parametrize("kind", ["before-after", "sequence"])
def test_script_label_is_escaped_exactly_once(kind):
    spec = _hostile_specs(_SCRIPT_LABEL)[kind]
    svg = _render(spec)
    shown = _sanitized_label(kind, explain_spec.sanitize_spec(spec))
    assert svg.count(html.escape(shown, quote=True)) == 1
    assert "&amp;lt;" not in svg and "&amp;gt;" not in svg, "double escape"
    assert "<script" not in svg.lower() and "</script" not in svg.lower()


@pytest.mark.parametrize("kind", ["before-after", "sequence"])
def test_url_label_renders_offline(kind):
    _render(_hostile_specs("see https://cdn.example/x.js")[kind])


# ---------------------------------------------------------------------------
# unusable spec: the existing empty SVG
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("spec", [
    _before_after(nodes="explain_spec"),
    _sequence(nodes=None),
    _sequence(svg="<svg/>"),
    _before_after(mermaid="graph TD; a-->b"),
])
def test_unusable_spec_gives_the_empty_svg(spec):
    assert _render(spec) == spec_svg(None)
