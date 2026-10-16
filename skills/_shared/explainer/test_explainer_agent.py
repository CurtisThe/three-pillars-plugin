"""test_explainer_agent.py — the `tp-explainer` agent charter and its registrations.

Covers explainer-agent plan Task 7.4 (detailed-design §Routing / §Agent):
  - the frontmatter carries the policy model and effort
    (`model_policy.agent_spec("tp-explainer")`) and the tools Read and Write only;
  - the body names a draft mode and a check mode, names the envelope schema
    (`explain_envelope.SCHEMA`) as its only output, says it reads only the request
    bundle, points at the STE guide, and holds the never-kill-by-name line;
  - the agent is listed in `.claude-plugin/plugin.json` and the agent/manifest
    drift check (`agent_variants.check`) is clean.

The expected model, effort and schema come from the shipped modules, not copied
literals; prose checks look for the named phrase, not a whole sentence
(skills/_shared/test-fragility.md). Reads only the plugin tree (agents/ and
.claude-plugin/), never the repo's doc tree.
"""
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import agent_variants  # noqa: E402
import explain_envelope  # noqa: E402
import model_policy  # noqa: E402
from weight_class import parse_frontmatter  # noqa: E402

ROOT = agent_variants.FRAMEWORK_ROOT
NAME = "tp-explainer"
AGENT = ROOT / "agents" / f"{NAME}.md"


def _text() -> str:
    assert AGENT.is_file(), AGENT
    return AGENT.read_text(encoding="utf-8")


def _body() -> str:
    return _text().split("\n---\n", 1)[1]


def _lines_with(phrase: str) -> list[str]:
    return [ln.lower() for ln in _body().splitlines() if phrase.lower() in ln.lower()]


def test_frontmatter_matches_the_policy_row():
    fm = parse_frontmatter(_text())
    spec = model_policy.agent_spec(NAME)
    assert fm["name"] == NAME
    assert (fm["model"], fm["effort"]) == ("sonnet", "medium")
    assert (fm["model"], fm["effort"]) == (spec["model"], spec["effort"])
    assert json.loads(fm["tools"]) == ["Read", "Write"]


def test_body_names_draft_and_check_modes():
    body = _body().lower()
    assert "draft mode" in body
    assert "check mode" in body


def test_envelope_is_the_only_output():
    lines = _lines_with(explain_envelope.SCHEMA)
    assert lines, f"{explain_envelope.SCHEMA} not named"
    assert any("only" in ln for ln in lines)


def test_reads_only_the_request_bundle():
    assert any("only" in ln for ln in _lines_with("request bundle"))


def test_points_at_the_ste_guide():
    assert "skills/_shared/ste-writing.md" in _body()


def test_carries_the_never_kill_by_name_line():
    assert "Never kill processes by name or pattern" in _body()


def test_listed_in_plugin_json():
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert f"./agents/{NAME}.md" in manifest["agents"]


def test_agent_drift_check_is_clean():
    assert agent_variants.check(ROOT) == []
