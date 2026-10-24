"""test_wt_layout_hook_registration.py — the wt-layout hook ships in the manifest.

design: worktrees-under-wt-only (Task 1.3). The manifest is parsed, never
text-matched; each registered command is then run from this checkout with
`CLAUDE_PLUGIN_ROOT` set, as the plugin cache runs it.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "skills" / "_shared" / "hooks" / "claude-code-hooks.json"
SUFFIX = '/skills/_shared/wt_layout_hook.py"'


def _entries():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]


def _commands(matcher):
    found = [e for e in _entries() if e["matcher"] == matcher]
    assert len(found) == 1, "expected exactly one %s matcher entry" % matcher
    return [h for h in found[0]["hooks"] if str(h.get("command", "")).endswith(SUFFIX)]


def _run(hook):
    iso = "work" + "tree"
    payload = json.dumps({"tool_name": "Agent", "tool_input": {
        "prompt": "x", "isolation": iso}})
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(ROOT), "TP_DESIGN_RUN": "1"}
    env.pop("TP_WT_LAYOUT", None)
    return subprocess.run(["bash", "-c", hook["command"]], input=payload,
                          capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=60)


def _assert_deny(hook):
    r = _run(hook)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"


def test_registered_on_the_single_bash_entry():
    hooks = _commands("Bash")
    assert len(hooks) == 1, "Bash entry must run wt_layout_hook.py exactly once"


def test_registered_on_agent_task_matcher():
    assert len(_commands("Agent|Task")) == 1


def test_command_is_well_formed():
    for matcher in ("Bash", "Agent|Task"):
        hook = _commands(matcher)[0]
        assert hook["type"] == "command"
        assert hook["command"].startswith('python3 "${CLAUDE_PLUGIN_ROOT:-')
        assert hook["timeout"]


def test_bash_registered_command_denies_isolation_payload():
    _assert_deny(_commands("Bash")[0])


def test_agent_registered_command_denies_isolation_payload():
    _assert_deny(_commands("Agent|Task")[0])
