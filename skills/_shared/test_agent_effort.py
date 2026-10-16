"""Agent effort / variant / manifest sync guards (design: run-throughput 3.4)."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_variants  # noqa: E402

ROOT = agent_variants.FRAMEWORK_ROOT
VARIANTS = [f"tp-task-worker-{r}" for r in ("local-medium", "local-xhigh", "sonnet-medium", "sonnet-xhigh")]


def _body(text: str) -> str:
    return text.split("\n---\n", 1)[1]


def _copy(tmp_path: Path) -> Path:
    (tmp_path / ".claude-plugin").mkdir()
    shutil.copytree(ROOT / "agents", tmp_path / "agents")
    shutil.copy(ROOT / ".claude-plugin" / "plugin.json", tmp_path / ".claude-plugin" / "plugin.json")
    return tmp_path


def test_live_check_clean():
    assert agent_variants.check(ROOT) == []


def test_live_agents_and_plugin_json():
    files = sorted(p.name for p in (ROOT / "agents").glob("*.md"))
    # + opus-medium/-xhigh (Q4), -deep (Q2), tp-drafter + tp-drafter-xhigh, tp-finalizer,
    # tp-spawn-host, tp-explainer, + tp-phase-checker, + the 19 generated Strata `-medium`
    # variants (18 council personas + tp-review-confirmer-medium; strata-effort-every-call 2.1)
    assert len(files) == 58
    listed = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["agents"]
    assert listed == [f"./agents/{n}" for n in files]


def test_variant_bodies_match_base():
    base = _body((ROOT / "agents" / "tp-task-worker.md").read_text(encoding="utf-8"))
    for v in VARIANTS:
        assert _body((ROOT / "agents" / f"{v}.md").read_text(encoding="utf-8")) == base


def test_hand_edited_variant_effort_reported(tmp_path):
    fw = _copy(tmp_path)
    f = fw / "agents" / "tp-task-worker-local-medium.md"
    f.write_text(f.read_text(encoding="utf-8").replace("effort: medium", "effort: low", 1), encoding="utf-8")
    assert agent_variants.check(fw) != []


def test_agent_without_policy_reported(tmp_path):
    fw = _copy(tmp_path)
    (fw / "agents" / "tp-bogus.md").write_text("---\nname: tp-bogus\nmodel: opus\n---\nb\n", encoding="utf-8")
    assert any("tp-bogus" in line for line in agent_variants.check(fw))


def test_stale_plugin_json_reported(tmp_path):
    fw = _copy(tmp_path)
    pj = fw / ".claude-plugin" / "plugin.json"
    data = json.loads(pj.read_text(encoding="utf-8"))
    data["agents"] = data["agents"][:-1]
    pj.write_text(json.dumps(data), encoding="utf-8")
    assert agent_variants.check(fw) != []
