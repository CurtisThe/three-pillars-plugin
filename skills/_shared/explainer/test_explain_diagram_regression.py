"""test_explain_diagram_regression.py — the ripley-app brief specs render connected.

Covers explainer-diagram-fidelity plan Task 1.10 (design Part 6): two specs
reconstructed from the rendered ripley-app comment (dict-shaped nodes and
edges) come out of mermaid and SVG connected and dict-free, and pass the gate.
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import copy  # noqa: E402

import explain_diagram_check as edc  # noqa: E402
import explain_gate as eg  # noqa: E402
import pytest  # noqa: E402
from explain_mermaid import spec_mermaid  # noqa: E402
from explain_svg import spec_svg  # noqa: E402
from test_explain_gate import _envelope, _request  # noqa: E402

LABEL = "Browser: home screen"


def _nodes():
    return [
        {"id": "browser", "label": LABEL},
        {"id": "api", "label": "API server"},
        {"id": "auth", "label": "Auth service"},
        {"id": "db", "label": "Database"},
        {"id": "cache", "label": "Cache"},
    ]


FLOW = {
    "kind": "flow",
    "nodes": _nodes(),
    "edges": [
        {"from": "browser", "to": "api"},
        {"from": "api", "to": "auth"},
        {"from": "api", "to": "db"},
        {"from": "api", "to": "cache"},
    ],
}
DECISION = {
    "kind": "decision",
    "nodes": _nodes(),
    "edges": [
        {"from": "browser", "to": "api"},
        {"from": "api", "to": "auth"},
        {"from": "auth", "to": "db"},
        {"from": "db", "to": "cache"},
    ],
}
SPECS = [pytest.param(FLOW, id="flow"), pytest.param(DECISION, id="decision")]


@pytest.mark.parametrize("spec", SPECS)
def test_mermaid_is_connected_and_dict_free(spec):
    text = spec_mermaid(copy.deepcopy(spec))
    assert text is not None
    assert "{'" not in text and "'id':" not in text
    assert LABEL in text
    assert text.count("-->") >= len(spec["edges"])


@pytest.mark.parametrize("spec", SPECS)
def test_svg_is_dict_free(spec):
    svg = spec_svg(copy.deepcopy(spec))
    assert "{'" not in svg and "'id':" not in svg
    assert LABEL in svg


@pytest.mark.parametrize("spec", SPECS)
def test_spec_passes_the_diagram_check(spec):
    assert edc.problem(copy.deepcopy(spec)) is None


@pytest.mark.parametrize("spec", SPECS)
def test_spec_passes_the_gate(spec):
    env = _envelope()
    env["diagram_specs"] = [copy.deepcopy(spec)]
    result = eg.run_gates(env, _request())
    assert "diagram:0" not in result["failures"]
    assert result["diagram_reasons"] == [None]


def test_edgeless_copy_of_the_flow_is_rejected_with_a_reason():
    bare = copy.deepcopy(FLOW)
    del bare["edges"]
    assert spec_mermaid(bare) is None
    assert edc.problem(bare) is not None
