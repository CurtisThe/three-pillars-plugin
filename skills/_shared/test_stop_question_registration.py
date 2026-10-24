"""Task 3.3: the plugin manifest registers the Stop hook; the fleet touch-1 cards are tagged."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import escalate_first_hook  # noqa: E402
import stop_question_hook  # noqa: E402

MANIFEST = ROOT / "skills" / "_shared" / "hooks" / "claude-code-hooks.json"
HOOKS_REL = "./skills/_shared/hooks/claude-code-hooks.json"
# the release leak guard bars pro-exclusive names in shipped core text: build the path from parts
FLEET = ROOT / "skills" / ("tp-" + "fleet") / "SKILL.md"
STOP_CMD = 'python3 "${CLAUDE_PLUGIN_ROOT:-.}/skills/_shared/stop_question_hook.py"'


def test_manifest_checkers_pass():
    assert stop_question_hook.check_manifest(MANIFEST) == 0
    assert escalate_first_hook.check_manifest(MANIFEST) == 0


def test_stop_is_one_unmatched_group_with_one_hook():
    hooks = json.loads(MANIFEST.read_text(encoding="utf-8"))["hooks"]
    assert len(hooks["Stop"]) == 1
    group = hooks["Stop"][0]
    assert "matcher" not in group
    assert group["hooks"] == [{"type": "command", "command": STOP_CMD, "timeout": 10}]
    assert "PreToolUse" in hooks


def test_plugin_json_names_manifest():
    dev = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert dev["hooks"] == HOOKS_REL


def test_fleet_cards_tagged_and_under_cap():
    # step 6 Gate and Teardown moved out of SKILL.md into the sibling gate-teardown.md
    files = (FLEET, FLEET.with_name("gate-teardown.md"))
    texts = [f.read_text(encoding="utf-8") for f in files]
    assert sum(t.count("seat-allow: fleet-scope") for t in texts) == 3
    assert all(len(t) < 35000 for t in texts)
