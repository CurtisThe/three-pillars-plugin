"""test_create_fence_registration.py - the create fence is registered in the manifest (run-scratch-in-fence 1.5).

The manifest is parsed, never text-matched, and each registered command is then
run from this checkout with `CLAUDE_PLUGIN_ROOT` set, exactly as the plugin
cache runs it. The hook only ever sees fixture JSON on stdin; the project it
judges is a throwaway repo under `tmp_path`, and nothing is created.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from test_create_fence_hook import TMP, make_env, make_repo

SHARED = Path(__file__).resolve().parent
ROOT = SHARED.parents[1]
MANIFEST = SHARED / "hooks" / "claude-code-hooks.json"
sys.path.insert(0, str(SHARED))

import safety_gate  # noqa: E402

SCRIPT = "create_fence_hook.py"
COMMAND = 'python3 "${CLAUDE_PLUGIN_ROOT:-.}/skills/_shared/create_fence_hook.py"'
FILE_MATCHER = "Write|Edit|NotebookEdit"
_UNSET = ("TP_DESIGN_RUN", "TP_CREATE_FENCE", "TP_DELETE_FENCE", "CLAUDE_PROJECT_DIR")


def _entries():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]


def _entry(matcher):
    found = [e for e in _entries() if e["matcher"] == matcher]
    assert len(found) == 1, "expected exactly one %s matcher entry" % matcher
    return found[0]


def _script(hook):
    return Path(hook["command"].rstrip('"')).name


def test_one_new_entry_registers_the_hook_for_the_file_tools():
    assert _entry(FILE_MATCHER)["hooks"] == [
        {"type": "command", "command": COMMAND, "timeout": 10}]


def test_the_bash_entry_runs_the_create_fence_once_after_the_delete_fence():
    hooks = _entry("Bash")["hooks"]
    names = [_script(h) for h in hooks]
    assert names.count(SCRIPT) == 1
    assert names.index("delete_fence_hook.py") < names.index(SCRIPT)
    hook = hooks[names.index(SCRIPT)]
    assert hook == {"type": "command", "command": COMMAND, "timeout": 10}


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    return make_repo(tmp_path_factory.mktemp("create-fence-registration"))


def _run(repo, matcher, tool, tool_input):
    hooks = _entry(matcher)["hooks"]
    command = hooks[[_script(h) for h in hooks].index(SCRIPT)]["command"]
    env = {k: v for k, v in os.environ.items() if k not in _UNSET}
    env.update(make_env(repo), CLAUDE_PLUGIN_ROOT=str(ROOT))
    payload = {"tool_name": tool, "tool_input": tool_input, "cwd": repo["a"],
               "session_id": "sess-reg", "transcript_path": "/nonexistent/projects/p/s.jsonl"}
    return subprocess.run(["bash", "-c", command], input=json.dumps(payload), cwd=repo["a"],
                          capture_output=True, text=True, env=env, timeout=60)


def _decision(proc):
    assert proc.returncode == 0, proc.stderr
    if not proc.stdout.strip():
        return "allow"
    return json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"]


def test_the_registered_file_tool_command_denies_outside_and_allows_inside(repo):
    outside = os.path.join(repo["home"], ".cache_tel11.json")
    inside = os.path.join(repo["run"], "f")
    assert _decision(_run(repo, FILE_MATCHER, "Write", {"file_path": outside})) == "deny"
    assert _decision(_run(repo, FILE_MATCHER, "Write", {"file_path": inside})) == "allow"


def test_the_registered_bash_command_denies_outside_and_allows_inside(repo):
    outside = {"command": "touch %s/x" % TMP}
    inside = {"command": "touch %s/x" % repo["run"]}
    assert _decision(_run(repo, "Bash", "Bash", outside)) == "deny"
    assert _decision(_run(repo, "Bash", "Bash", inside)) == "allow"
    assert _decision(_run(repo, "Bash", "Bash", {"command": "ls -la"})) == "allow"


def test_a_new_fence_module_is_a_gate_path_by_the_family_glob():
    assert safety_gate.touches_gate(["skills/_shared/create_fence_future_module.py"]) is True
    assert safety_gate.touches_gate(["skills/_shared/test_create_fence_future_module.py"]) is False
