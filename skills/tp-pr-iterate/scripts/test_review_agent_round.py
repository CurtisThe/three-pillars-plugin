"""test_review_agent_round.py — review angles run -deep/xhigh on round 1, high after (Q2).

design: run-throughput (operator ruling Q2, PR #178 fix pass)

Behavior: the one selector `angles.review_agent(round)` picks the agent; both agents
pass `dispatch_select`'s review floor; and `round_scratch.prepare` — the manifest both
tp-pr-iterate and Tier 7 spawn from — carries the selected agent's resolved reference
per angle (round 1 `-deep`, round 2 the base), against a fixture plugin root.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "_shared"))

import angles  # noqa: E402
import dispatch_select  # noqa: E402
import model_policy  # noqa: E402
import round_scratch as rs  # noqa: E402
from test_agent_ref import fixture_root  # noqa: E402

PR = "https://github.com/o/r/pull/42"
BOTH = ("tp-review-confirmer", "tp-review-confirmer-deep")


def test_round_one_is_deep_xhigh_later_rounds_high():
    assert angles.review_agent(1) == "tp-review-confirmer-deep"
    assert model_policy.agent_spec(angles.review_agent(1))["effort"] == "xhigh"
    for n in (2, 3, 7):
        assert angles.review_agent(n) == "tp-review-confirmer"
        assert model_policy.agent_spec(angles.review_agent(n))["effort"] == "high"


def test_both_agents_pass_the_review_floor():
    for agent in BOTH:
        assert dispatch_select.enforce_floor("review", agent) == (agent, None)
    assert model_policy.floor("review")["effort"] == "high"


def _prep(root, plugin_root):
    return rs.prepare(root, PR, angles.DEFAULT_ANGLES, base="b0", head="h1", effort="high",
                      state_path=str(root / "s.json"), log_path=str(root / "l.md"),
                      plugin_root=plugin_root)


def test_manifest_carries_the_selected_reference_per_round(tmp_path):
    plugin = fixture_root(tmp_path, agents=BOTH)
    proof = tmp_path / "proof"
    r1 = _prep(proof, plugin)
    got1 = json.loads((r1 / "angles.json").read_text(encoding="utf-8"))["angles"]
    assert {(e["agent"], e["agent_ref"]) for e in got1} == {
        ("tp-review-confirmer-deep", "three-pillars-pro:tp-review-confirmer-deep")}
    (r1 / "tail").mkdir(exist_ok=True)
    (r1 / "tail" / "envelope.json").write_text(json.dumps({"action": "fix"}), encoding="utf-8")
    r2 = _prep(proof, plugin)
    got2 = json.loads((r2 / "angles.json").read_text(encoding="utf-8"))["angles"]
    assert {(e["agent"], e["agent_ref"]) for e in got2} == {
        ("tp-review-confirmer", "three-pillars-pro:tp-review-confirmer")}


def test_unresolvable_review_agent_refuses_prepare(tmp_path):
    plugin = fixture_root(tmp_path, agents=("tp-review-confirmer",))  # no -deep shipped
    try:
        _prep(tmp_path / "proof", plugin)
    except ValueError as exc:
        assert "agent-unresolved: tp-review-confirmer-deep" in str(exc)
    else:
        raise AssertionError("prepare must refuse an unresolvable review agent")


# --- review-proof-out-of-tree 1.5: the confirmers drop Write -----------------------

AGENTS_DIR = HERE.parents[2] / "agents"


def test_both_confirmers_have_no_file_write_tool_and_deliver_via_put():
    from weight_class import parse_frontmatter
    for name in BOTH:
        text = (AGENTS_DIR / f"{name}.md").read_text(encoding="utf-8")
        assert json.loads(parse_frontmatter(text)["tools"]) == ["Read", "Grep", "Glob", "Bash"]
        body = text.split("\n---\n", 1)[1]
        assert "round_scratch.py put" in body
        bash_line = next(ln for ln in body.splitlines()
                         if "Bash is for read-only execution only" in ln)
        assert "put" in bash_line.split("Bash is for read-only execution only", 1)[1]
        assert "reply_path` and nothing else" not in body
