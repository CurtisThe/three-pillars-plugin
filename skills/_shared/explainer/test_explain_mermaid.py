"""test_explain_mermaid.py — mermaid from the same sanitized diagram spec.

Covers explainer-agent plan Task 2.3 (detailed-design: "explain_mermaid.py:
spec_mermaid(spec) -> str | None, from the same sanitized spec. Labels escaped
("→#quot;, <>, backticks, []{}()|;)"; design: "One diagram spec renders to
offline SVG and to valid mermaid"):
  - each of the five kinds opens with its mermaid header line;
  - every other line is a statement of that kind's grammar, node ids are
    n<digits>, and the declared labels, edges and messages are the spec's;
  - before-after has one classDef per status and each node takes its status;
  - a hostile label comes out with " as #quot; and none of <>`[]{}()|; raw;
  - no output line holds a raw <;
  - an unusable spec gives None;
  - guard: one before-after spec gives offline SVG and valid mermaid.

The output is parsed with a small closed grammar of the statements each kind
allows (skills/_shared/test-fragility.md: assert on structure, never on
pinned text).
"""
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest  # noqa: E402

import explain_offline  # noqa: E402
from explain_mermaid import spec_mermaid  # noqa: E402
from explain_spec_ext import STATUSES  # noqa: E402
from explain_svg import spec_svg  # noqa: E402

KINDS = ("flow", "decision", "state", "before-after", "sequence")
HEADER = {
    "flow": "flowchart LR",
    "decision": "flowchart TD",
    "state": "stateDiagram-v2",
    "before-after": "flowchart LR",
    "sequence": "sequenceDiagram",
}

# The characters detailed-design.md says a label may not carry raw.
_ESCAPED = set('"<>`[]{}()|;')
_ENTITY_RE = re.compile(r"#\w+;")
_HOSTILE = 'hostile "quote" <b> `tick` [x] {y} (z) | w; v'

# ---------------------------------------------------------------------------
# Example specs, one per kind, taken from the design's own pipeline
# ---------------------------------------------------------------------------

EXAMPLES = {
    "flow": {
        "kind": "flow",
        "nodes": ["request", "draft", "gate", "check", "render", "deliver"],
        "edges": [["request", "draft"], ["draft", "gate"], ["gate", "check"],
                  ["check", "render"], ["render", "deliver"]],
    },
    "decision": {
        "kind": "decision",
        "nodes": ["summary supported", "finalize", "facts-only"],
        "edges": [["summary supported", "finalize"],
                  ["summary supported", "facts-only"]],
    },
    "state": {
        "kind": "state",
        "nodes": ["briefed", "stale", "refreshed"],
        "edges": [["briefed", "stale"], ["stale", "refreshed"],
                  ["refreshed", "stale"]],
        "labels": {"stale": "head moved"},
    },
    "before-after": {
        "kind": "before-after",
        "nodes": ["explain_spec", "explain_spec_ext", "explain_svg", "pro_copy"],
        "edges": [["explain_spec", "explain_spec_ext"],
                  ["explain_svg", "explain_spec"]],
        "labels": {"pro_copy": "pro diagram copy"},
        "status": {"explain_spec": "changed", "explain_spec_ext": "added",
                   "explain_svg": "existing", "pro_copy": "removed"},
    },
    "sequence": {
        "kind": "sequence",
        "nodes": ["seat", "explainer", "forge"],
        "messages": [["seat", "explainer", "draft brief"],
                     ["explainer", "forge", "post comment"],
                     ["forge", "seat", "comment url"]],
    },
}


def _shown(spec: dict, node: str) -> str:
    return spec.get("labels", {}).get(node, node)


# ---------------------------------------------------------------------------
# A closed grammar of the statements each kind may emit
# ---------------------------------------------------------------------------

_ID = r"(n\d+)"
_FLOW_NODE = re.compile(rf'^{_ID}\["([^"]*)"\](?::::([\w-]+))?$')
_ARROW = re.compile(rf"^{_ID}\s*-->\s*{_ID}$")
_CLASSDEF = re.compile(r"^classDef ([\w-]+) \S.*$")
_CLASS = re.compile(rf"^class {_ID} ([\w-]+)$")
_STATE_NODE = re.compile(rf'^state "([^"]*)" as {_ID}$')
_PARTICIPANT = re.compile(rf"^participant {_ID} as (\S.*)$")
_MESSAGE = re.compile(rf"^{_ID}\s*->>\s*{_ID}\s*:\s*(.*)$")


def _flow_node(m, out):
    out["labels"][m[1]] = m[2]
    if m[3]:
        out["classes"][m[1]] = m[3]


_RULES = {
    "node": (_FLOW_NODE, _flow_node),
    "arrow": (_ARROW, lambda m, out: out["edges"].append((m[1], m[2]))),
    "classdef": (_CLASSDEF, lambda m, out: out["classdefs"].append(m[1])),
    "class": (_CLASS, lambda m, out: out["classes"].__setitem__(m[1], m[2])),
    "state": (_STATE_NODE, lambda m, out: out["labels"].__setitem__(m[2], m[1])),
    "participant": (_PARTICIPANT,
                    lambda m, out: out["labels"].__setitem__(m[1], m[2])),
    "message": (_MESSAGE,
                lambda m, out: out["messages"].append((m[1], m[2], m[3]))),
}
_GRAMMAR = {
    "flow": ("node", "arrow"),
    "decision": ("node", "arrow"),
    "state": ("state", "arrow"),
    "before-after": ("node", "arrow", "classdef", "class"),
    "sequence": ("participant", "message"),
}


def _parse(kind: str, text) -> dict:
    """Check text against kind's grammar; return what it declares, by id."""
    assert isinstance(text, str), text
    lines = [ln.strip() for ln in text.splitlines()]
    assert lines and lines[0] == HEADER[kind]
    assert not [ln for ln in lines if "<" in ln], "raw <"
    out = {"labels": {}, "edges": [], "messages": [], "classdefs": [],
           "classes": {}}
    for line in filter(None, lines[1:]):
        for rule in _GRAMMAR[kind]:
            regex, record = _RULES[rule]
            m = regex.match(line)
            if m:
                record(m, out)
                break
        else:
            raise AssertionError(f"not a {kind} statement: {line!r}")
    used = {i for e in out["edges"] for i in e}
    used |= {i for msg in out["messages"] for i in msg[:2]}
    used |= set(out["classes"])
    assert used <= set(out["labels"]), "an edge or class names an undeclared id"
    return out


def _by_label(parsed: dict) -> dict:
    """The parsed diagram in label terms (ids resolved through declarations)."""
    lab = parsed["labels"]
    return {
        "labels": sorted(lab.values()),
        "edges": {(lab[s], lab[d]) for s, d in parsed["edges"]},
        "messages": [(lab[s], lab[d], t) for s, d, t in parsed["messages"]],
        "classes": {lab[i]: c for i, c in parsed["classes"].items()},
    }


# ---------------------------------------------------------------------------
# One example per kind
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", KINDS)
def test_each_kind_opens_with_its_header(kind):
    text = spec_mermaid(EXAMPLES[kind])
    assert text.splitlines()[0].strip() == HEADER[kind]


@pytest.mark.parametrize("kind", KINDS)
def test_each_kind_declares_every_node_label(kind):
    spec = EXAMPLES[kind]
    got = _by_label(_parse(kind, spec_mermaid(spec)))
    assert got["labels"] == sorted(_shown(spec, n) for n in spec["nodes"])


@pytest.mark.parametrize("kind", ["flow", "decision", "state", "before-after"])
def test_each_graph_kind_draws_the_spec_edges(kind):
    spec = EXAMPLES[kind]
    got = _by_label(_parse(kind, spec_mermaid(spec)))
    want = {(_shown(spec, s), _shown(spec, d)) for s, d in spec["edges"]}
    assert got["edges"] == want


def test_sequence_keeps_message_order():
    spec = EXAMPLES["sequence"]
    got = _by_label(_parse("sequence", spec_mermaid(spec)))
    want = [(_shown(spec, s), _shown(spec, d), t) for s, d, t in spec["messages"]]
    assert got["messages"] == want


def test_before_after_has_one_classdef_per_status():
    parsed = _parse("before-after", spec_mermaid(EXAMPLES["before-after"]))
    assert sorted(parsed["classdefs"]) == sorted(STATUSES)


def test_before_after_node_takes_its_status_class():
    spec = EXAMPLES["before-after"]
    got = _by_label(_parse("before-after", spec_mermaid(spec)))
    want = {_shown(spec, n): s for n, s in spec["status"].items()}
    assert got["classes"] == want


# ---------------------------------------------------------------------------
# Hostile labels: escaped for mermaid
# ---------------------------------------------------------------------------

def _hostile_spec(kind: str) -> dict:
    spec = dict(EXAMPLES[kind])
    first = spec["nodes"][0]
    spec["labels"] = {first: _HOSTILE}
    if kind == "sequence":
        msgs = list(spec["messages"])
        msgs[0] = [msgs[0][0], msgs[0][1], _HOSTILE]
        spec["messages"] = msgs
    return spec


def _assert_escaped(content: str):
    assert "#quot;" in content
    raw = _ENTITY_RE.sub("", content)
    assert not set(raw) & _ESCAPED, raw


@pytest.mark.parametrize("kind", KINDS)
def test_hostile_node_label_is_escaped(kind):
    parsed = _parse(kind, spec_mermaid(_hostile_spec(kind)))
    hostile = [v for v in parsed["labels"].values() if v.startswith("hostile")]
    assert len(hostile) == 1
    _assert_escaped(hostile[0])


def test_hostile_message_label_is_escaped():
    parsed = _parse("sequence", spec_mermaid(_hostile_spec("sequence")))
    texts = [t for _, _, t in parsed["messages"] if t.startswith("hostile")]
    assert len(texts) == 1
    _assert_escaped(texts[0])


# ---------------------------------------------------------------------------
# Unusable specs give None
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("spec", [
    None,
    "graph TD; a-->b",
    {"kind": "pie", "nodes": ["a"]},
    {"kind": "flow", "nodes": "request"},
    {"kind": "sequence", "nodes": None},
    dict(EXAMPLES["flow"], mermaid="graph TD; a-->b"),
    dict(EXAMPLES["before-after"], svg="<svg/>"),
])
def test_unusable_spec_gives_none(spec):
    assert spec_mermaid(spec) is None


# ---------------------------------------------------------------------------
# The one-spec guard: SVG and mermaid from the same spec
# ---------------------------------------------------------------------------

def test_one_before_after_spec_gives_offline_svg_and_valid_mermaid():
    spec = EXAMPLES["before-after"]
    explain_offline.assert_offline(spec_svg(spec))
    parsed = _parse("before-after", spec_mermaid(spec))
    assert sorted(parsed["classdefs"]) == sorted(STATUSES)


@pytest.mark.parametrize("kind", KINDS)
def test_every_example_also_renders_offline_svg(kind):
    explain_offline.assert_offline(spec_svg(EXAMPLES[kind]))
