"""test_explain_gate_diagram.py — the gate runs the diagram check and names the reason.

Covers explainer-diagram-fidelity plan Task 1.5 (design Part 3 — Gate + check
mode): run_gates decides each diagram with explain_diagram_check.problem, so a
diagram that sanitize_spec would reject (an edge-less two-node flow) or keeps
but cannot draw connected fails with diagram:<i>; run_gates returns one reason
slug (or None) per diagram under "diagram_reasons"; rewrite_prompt takes an
optional diagram_reasons and states the reason sentence on the diagram:<i>
line; cmd_gate carries diagram_reasons.

Envelopes and requests come from the neighbouring gate / CLI test builders.
Assertions are on codes, slugs and the REASONS sentence the module owns
(skills/_shared/test-fragility.md); no prose is pinned here.
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import explain_diagram_check as edc  # noqa: E402
import explain_gate as eg  # noqa: E402
from test_explain_cli import repo, run, write_json  # noqa: E402,F401 — repo is a fixture
from test_explain_gate import _envelope, _request  # noqa: E402

NO_EDGE_FLOW = {"kind": "flow", "nodes": ["a", "b"]}


def _with_diagram(spec):
    env = _envelope()
    env["diagram_specs"] = [spec]
    return env


def _line_for(prompt, code):
    lines = [ln for ln in prompt.splitlines() if f"`{code}`" in ln]
    assert len(lines) == 1, prompt
    return lines[0]


def test_edgeless_two_node_flow_fails_with_its_reason():
    result = eg.run_gates(_with_diagram(NO_EDGE_FLOW), _request())
    assert result["pass"] is False
    assert "diagram:0" in result["failures"]
    assert result["diagrams_ok"] == [False]
    assert result["diagram_reasons"] == ["no-edges"]


def test_good_diagram_has_no_reason():
    result = eg.run_gates(_envelope(), _request())
    assert result["pass"] is True
    assert result["diagram_reasons"] == [None]


def test_orphan_node_is_a_failure_sanitize_would_keep():
    spec = {"kind": "flow", "nodes": ["a", "b", "c"], "edges": [["a", "b"]]}
    result = eg.run_gates(_with_diagram(spec), _request())
    assert result["failures"] == ["diagram:0"]
    assert result["diagrams_ok"] == [False]
    assert result["diagram_reasons"] == ["orphan-node"]


def test_no_diagram_list_gives_no_reasons():
    env = _envelope()
    env["diagram_specs"] = "nope"
    assert eg.run_gates(env, _request())["diagram_reasons"] == []


def test_rewrite_prompt_states_the_reason_on_the_diagram_line():
    result = eg.run_gates(_with_diagram(NO_EDGE_FLOW), _request())
    prompt = eg.rewrite_prompt(result["failures"], result["diagram_reasons"])
    assert edc.REASONS["no-edges"] in _line_for(prompt, "diagram:0")
    assert eg.ONLY_REWRITE in prompt


def test_rewrite_prompt_without_reasons_works_as_before():
    failures = ["missing-section:why", "diagram:0"]
    prompt = eg.rewrite_prompt(failures)
    assert "`missing-section:why`" in prompt
    assert edc.REASONS["no-edges"] not in _line_for(prompt, "diagram:0")
    assert prompt.rstrip().endswith(eg.ONLY_REWRITE)


def test_cmd_gate_output_carries_diagram_reasons(capsys, repo, tmp_path):
    req = write_json(tmp_path / "req" / "request.json", _request())
    env = write_json(tmp_path / "req" / "envelope.json", _with_diagram(NO_EDGE_FLOW))
    code, out = run(capsys, repo, "gate", "--request", req, "--envelope", env)
    assert code == 3
    assert out["diagram_reasons"] == ["no-edges"]
    assert edc.REASONS["no-edges"] in _line_for(out["rewrite_prompt"], "diagram:0")


def test_cmd_gate_pass_carries_null_reasons(capsys, repo, tmp_path):
    req = write_json(tmp_path / "req" / "request.json", _request())
    env = write_json(tmp_path / "req" / "envelope.json", _envelope())
    code, out = run(capsys, repo, "gate", "--request", req, "--envelope", env)
    assert code == 0
    assert out["diagram_reasons"] == [None]
