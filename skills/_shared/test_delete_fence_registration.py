"""test_delete_fence_registration.py — the delete fence is the fourth Bash hook in the manifest.

design: delete-fence-own-tree (Task 1.9). The manifest is parsed, never
text-matched; the registered command is then actually run from this checkout
with `CLAUDE_PLUGIN_ROOT` set, exactly as the plugin cache runs it. The only
thing the hook ever sees is fixture JSON on stdin: nothing is deleted, and the
project it judges is a throwaway repo under pytest's `tmp_path`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "skills" / "_shared" / "hooks" / "claude-code-hooks.json"
sys.path.insert(0, str(ROOT / "skills" / "_shared" / "fixtures"))

from delete_fence_repo import build  # noqa: E402

BASH_HOOKS = ("reviewer_delete_hook.py", "kill_guard_hook.py", "wait_ttl_hook.py",
              "delete_fence_hook.py")
COMMAND = 'python3 "${CLAUDE_PLUGIN_ROOT:-.}/skills/_shared/delete_fence_hook.py"'


def _bash_entry():
    entries = json.loads(MANIFEST.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    bash = [e for e in entries if e["matcher"] == "Bash"]
    assert len(bash) == 1, "the manifest gained a second Bash matcher entry"
    return bash[0]


def _script(hook):
    return Path(hook["command"].rstrip('"')).name


def test_delete_fence_is_the_fourth_bash_hook_after_wait_ttl():
    hooks = _bash_entry()["hooks"]
    assert [_script(h) for h in hooks][:4] == list(BASH_HOOKS)


def test_the_delete_fence_command_is_well_formed():
    hook = _bash_entry()["hooks"][3]
    assert hook["type"] == "command"
    assert hook["command"] == COMMAND
    assert hook["timeout"] == 10


def test_the_three_earlier_hooks_keep_their_shape():
    for hook in _bash_entry()["hooks"][:3]:
        assert hook["type"] == "command"
        assert hook["command"].startswith('python3 "${CLAUDE_PLUGIN_ROOT:-.}/')
        assert hook["timeout"] == 10


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    return build(tmp_path_factory.mktemp("fence-registration"))["repo"]


def _run(repo, command):
    env = {k: v for k, v in os.environ.items()
           if k not in ("TP_DESIGN_RUN", "TP_DELETE_FENCE", "CLAUDE_PROJECT_DIR")}
    env.update(CLAUDE_PLUGIN_ROOT=str(ROOT), CLAUDE_PROJECT_DIR=repo)
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": repo,
               "session_id": "sess-reg", "transcript_path": "/nonexistent/projects/p/s.jsonl"}
    hook = _bash_entry()["hooks"][3]["command"]
    return subprocess.run(["bash", "-c", hook], input=json.dumps(payload), capture_output=True,
                          text=True, env=env, cwd=repo, timeout=60)


def test_registered_command_denies_a_delete_outside_the_project(project):
    proc = _run(project, "rm -rf /home/x")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_registered_command_allows_a_delete_inside_the_project(project):
    proc = _run(project, "rm -rf build")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""
