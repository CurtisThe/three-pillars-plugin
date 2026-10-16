"""test_wait_ttl_hook.py — the wait-TTL PreToolUse Bash hook warns, never blocks.

design: prompt-cache-aware-dispatch (Task 1.3; Behavior 4).

Every case is a payload dict handed to `run`, plus one subprocess of the hook
script for the fail-open path. No command in a payload is ever executed here:
the commands are literal strings the hook only reads.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
sys.path.insert(0, str(_SHARED))

import wait_budget  # noqa: E402
import wait_ttl_hook as hook  # noqa: E402

SCRIPT = _SHARED / "wait_ttl_hook.py"
OVER = wait_budget.BASH_TIMEOUT_MS + 300000  # the plan's 600000
AT_BUDGET = wait_budget.BASH_TIMEOUT_MS      # the plan's 300000

# The plan's poll-loop commands: a one-line `until`, a `while`, the multi-line form.
UNTIL_PIPE = "until git -C /x log --oneline -1 | grep -q 2.1; do sleep 5; done"
WHILE_TRUE = "while true; do sleep 10; done"
UNTIL_MULTILINE = "until test -f m\ndo\n  sleep 5\ndone"

_SUBAGENT = {"agent_type": "three-pillars:tp-task-worker-local-medium", "agent_id": "toolu_x"}
# A missing `agent_type` cannot be told apart from a harness that never sends one,
# so both shapes warn: every session is checked (design, subagent scope).
AGENT_KEYS = [{}, dict(_SUBAGENT)]


def _payload(command="echo hi", timeout=None, background=None, **extra):
    tool_input = {"command": command}
    if timeout is not None:
        tool_input["timeout"] = timeout
    if background is not None:
        tool_input["run_in_background"] = background
    return {"tool_name": "Bash", "tool_input": tool_input, **extra}


def _warned(out):
    """The warning JSON, or a failure. Never a decision: the hook is warn-only.

    `systemMessage` is read by Claude Code only at the TOP LEVEL of the object;
    `hookSpecificOutput` carries the event name and `additionalContext`.
    """
    assert out, "expected a warning"
    assert "permissionDecision" not in out, out
    data = json.loads(out)
    assert set(data) == {"systemMessage", "hookSpecificOutput"}
    assert data["systemMessage"].strip()
    spec = data["hookSpecificOutput"]
    assert "systemMessage" not in spec
    assert spec["hookEventName"] == "PreToolUse"
    assert spec["additionalContext"].strip()
    return data


@pytest.mark.parametrize("command,timeout", [
    ("echo hi", OVER),
    (UNTIL_PIPE, None),
    (WHILE_TRUE, None),
    (UNTIL_MULTILINE, None),
])
@pytest.mark.parametrize("agent_keys", AGENT_KEYS)
def test_warns(command, timeout, agent_keys):
    out, rc = hook.run(_payload(command, timeout=timeout, **agent_keys))
    assert rc == 0
    data = _warned(out)
    message = data["systemMessage"]
    # the warning is actionable: background the command, wait through bg_wait.py
    assert "run_in_background" in message
    assert "bg_wait.py" in message
    assert str(wait_budget.WAIT_BUDGET_S) in message
    if agent_keys:
        assert agent_keys["agent_type"] in message


@pytest.mark.parametrize("command,timeout", [("echo hi", OVER), (UNTIL_PIPE, None),
                                             (WHILE_TRUE, None), (UNTIL_MULTILINE, None)])
def test_the_reason_names_what_triggered(command, timeout):
    """The timeout case says timeout, the loop case says the loop — not one generic line."""
    data = _warned(hook.run(_payload(command, timeout=timeout))[0])
    reason, other = ("timeout", "loop") if timeout is not None else ("loop", "timeout")
    ctx = data["hookSpecificOutput"]["additionalContext"]
    assert reason in ctx.lower()
    assert other not in ctx.lower()


@pytest.mark.parametrize("background", [False, 0])
def test_a_falsy_run_in_background_is_a_foreground_wait(background):
    """The key's presence is not a background start — only its JSON value is.

    `run_in_background: false` is the shape the certifier handed the hook: the call still
    blocks the turn, so an over-budget timeout on it warns like any other foreground wait.
    """
    out, rc = hook.run(_payload("echo hi", timeout=OVER, background=background))
    assert rc == 0
    assert json.loads(out)["systemMessage"].strip()


def test_run_in_background_true_with_the_same_timeout_stays_silent():
    """The same over-budget timeout on a real background start is not a wait."""
    assert hook.run(_payload("echo hi", timeout=OVER, background=True)) == ("", 0)


def test_the_threshold_is_strictly_above_the_budget():
    """300000 is allowed, 300001 warns — a threshold drifting to `>= 2 * 300000` goes red.

    The budget itself is the allowed maximum: the shipped prose re-runs `bg_wait.py` with Bash
    timeout 300000, so that call must never be warned about.
    """
    assert hook.run(_payload("echo hi", timeout=AT_BUDGET)) == ("", 0)
    out, rc = hook.run(_payload("echo hi", timeout=AT_BUDGET + 1))
    assert rc == 0
    assert json.loads(out)["systemMessage"].strip()


@pytest.mark.parametrize("tool_name,command,timeout,background", [
    ("Bash", "echo hi", AT_BUDGET, None),   # at the budget, not over it
    ("Bash", "echo hi", None, None),        # no timeout at all
    ("Bash", "echo hi", 7200000, True),     # background: the launch turn never waits
    ("Bash", "echo hi", OVER, True),        # the same timeout as the foreground case
    ("Bash", UNTIL_PIPE, None, True),       # the same loop, backgrounded
    ("Bash", "sleep 5", None, None),        # one sleep is not a poll loop
    ("Bash", "echo hi", "abc", None),       # a non-integer timeout is not a number
    ("Write", "echo hi", OVER, None),       # not a Bash call
])
def test_silent(tool_name, command, timeout, background):
    payload = _payload(command, timeout=timeout, background=background)
    payload["tool_name"] = tool_name
    assert hook.run(payload) == ("", 0)


@pytest.mark.parametrize("payload", [[], {}, None, "echo hi"])
def test_silent_on_a_payload_that_is_not_a_tool_call(payload):
    assert hook.run(payload) == ("", 0)


def test_fail_open_on_unparseable_stdin():
    r = subprocess.run([sys.executable, str(SCRIPT)], input="not json",
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""


def test_poll_loop_re_is_importable_for_the_prose_lint():
    """Task 1.6's prose lint reuses this pattern, so it is part of the module surface."""
    for command in (UNTIL_PIPE, WHILE_TRUE, UNTIL_MULTILINE):
        assert hook.POLL_LOOP_RE.search(command), command
    for command in ("sleep 5", "echo until; echo do; echo sleep",
                    "until test -f m; do echo x; done"):
        assert not hook.POLL_LOOP_RE.search(command), command
