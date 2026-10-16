"""test_explainer_agent_specs.py — `agents/tp-explainer.md` teaches one valid spec per kind.

Reads the doc, takes its fenced `json` blocks, and checks that each diagram kind
has exactly one block that parses, passes `explain_diagram_check.problem`, uses
the canonical shapes (plain-string ids, a `labels` map, `[from, to]` edges,
`[from, to, text]` messages), and that the connect-or-omit sentence is present.
"""
import json
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import agent_variants  # noqa: E402
import explain_diagram_check  # noqa: E402

import pytest  # noqa: E402

DOC = Path(agent_variants.FRAMEWORK_ROOT) / "agents" / "tp-explainer.md"
KINDS = ("flow", "decision", "state", "before-after", "sequence")
SENTENCE = "A diagram must show how things connect, or be left out."


def _specs():
    text = DOC.read_text(encoding="utf-8")
    return [json.loads(body) for body in re.findall(r"```json\s*\n(.*?)```", text, re.S)]


def _of_kind(kind):
    return [s for s in _specs() if isinstance(s, dict) and s.get("kind") == kind]


def test_doc_has_json_blocks():
    assert _specs()


@pytest.mark.parametrize("kind", KINDS)
def test_exactly_one_example_per_kind(kind):
    assert len(_of_kind(kind)) == 1


@pytest.mark.parametrize("kind", KINDS)
def test_example_passes_diagram_check(kind):
    assert explain_diagram_check.problem(_of_kind(kind)[0]) is None


@pytest.mark.parametrize("kind", KINDS)
def test_example_uses_canonical_shapes(kind):
    spec = _of_kind(kind)[0]
    assert all(isinstance(n, str) for n in spec["nodes"])
    labels = spec["labels"]
    assert isinstance(labels, dict)
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in labels.items())
    if kind == "sequence":
        assert all(
            isinstance(m, list) and len(m) == 3 and all(isinstance(x, str) for x in m)
            for m in spec["messages"]
        )
    else:
        assert all(
            isinstance(e, list) and len(e) == 2 and all(isinstance(x, str) for x in e)
            for e in spec["edges"]
        )


def test_doc_has_connect_or_omit_sentence():
    assert SENTENCE in DOC.read_text(encoding="utf-8")
