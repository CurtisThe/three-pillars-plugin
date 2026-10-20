"""test_wait_ttl_hook_registration.py — the wait-TTL hook ships in the hooks manifest.

design: prompt-cache-aware-dispatch (Task 1.3). The manifest is parsed, never
text-matched; the registered command is then actually run from this checkout
with `CLAUDE_PLUGIN_ROOT` set, exactly as the plugin cache runs it.

design: delete-fence-own-tree (Task 2.8). The registration test pins the
wait-TTL hook's *order* relative to the delete-fence hook, never its absolute
position — appending a hook to the manifest must not break this test.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "skills" / "_shared" / "hooks" / "claude-code-hooks.json"

OVER = 600000    # over wait_budget.BASH_TIMEOUT_MS: warns
UNDER = 120000   # well inside it: silent


def _bash_entry():
    entries = json.loads(MANIFEST.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    bash = [e for e in entries if e["matcher"] == "Bash"]
    assert len(bash) == 1, "the manifest gained a second Bash matcher entry"
    return bash[0]


def _wait_ttl_hook():
    for hook in _bash_entry()["hooks"]:
        if str(hook.get("command", "")).endswith('/skills/_shared/wait_ttl_hook.py"'):
            return hook
    raise AssertionError("no Bash hook command runs wait_ttl_hook.py")


def _payload(timeout):
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": "sleep 5",
                                                           "timeout": timeout}})


def _run(timeout):
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(ROOT)}
    return subprocess.run(["bash", "-c", _wait_ttl_hook()["command"]], input=_payload(timeout),
                          capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=60)


def _waits_before_the_fence(commands):
    """True when a wait_ttl command exists and precedes the delete_fence one."""
    def idx(suffix):
        for i, c in enumerate(commands):
            if str(c).endswith(suffix):
                return i
        return None

    wait = idx('/skills/_shared/wait_ttl_hook.py"')
    fence = idx('/skills/_shared/delete_fence_hook.py"')
    return wait is not None and fence is not None and wait < fence


def test_registered_beside_the_existing_bash_hooks():
    hooks = _bash_entry()["hooks"]
    commands = [h["command"] for h in hooks]
    assert hooks[0]["command"].endswith('/skills/_shared/reviewer_delete_hook.py"')
    assert any(c.endswith('/skills/_shared/kill_guard_hook.py"') for c in commands)
    assert _waits_before_the_fence(commands), (
        "wait_ttl_hook.py must be registered before delete_fence_hook.py")


def test_the_ordering_pin_survives_a_hook_appended_after_the_fence():
    """A position pin would break when the manifest grows; the order pin does not."""
    commands = [h["command"] for h in _bash_entry()["hooks"]]
    appended = commands + ['python3 "${CLAUDE_PLUGIN_ROOT:-.}/skills/_shared/'
                          'hypothetical_future_hook.py"']
    assert _waits_before_the_fence(commands)
    assert _waits_before_the_fence(appended)


def test_the_wait_ttl_command_is_well_formed():
    hook = _wait_ttl_hook()
    assert hook["type"] == "command"
    assert hook["command"].startswith('python3 "${CLAUDE_PLUGIN_ROOT:-')
    assert hook["timeout"], "a hook with no timeout can hang the session"


def test_registered_command_warns_over_the_budget():
    r = _run(OVER)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["systemMessage"].strip()
    assert data["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert data["hookSpecificOutput"]["additionalContext"].strip()
    assert "systemMessage" not in data["hookSpecificOutput"]
    assert "permissionDecision" not in r.stdout


def test_registered_command_is_silent_inside_the_budget():
    r = _run(UNDER)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == ""
