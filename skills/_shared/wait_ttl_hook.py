#!/usr/bin/env python3
"""wait_ttl_hook.py — warn-only PreToolUse Bash hook for the prompt-cache TTL.

design: prompt-cache-aware-dispatch (Task 1.3; Behavior 4)

A foreground Bash call that outlives `wait_budget.CACHE_TTL_S` (a `timeout`
above `wait_budget.BASH_TIMEOUT_MS`, or an `until`/`while … do sleep` poll loop)
lets the caller's prompt cache expire mid-wait, so the whole context is
re-written on wake. This hook names that shape and points at the cheap one —
start the command with `run_in_background`, then wait through
`skills/_shared/bg_wait.py`, one bounded call at a time.

It never blocks: the warning is a top-level `systemMessage` (Claude Code reads
it only there) plus `hookSpecificOutput.additionalContext`, and no
`permissionDecision` key is ever emitted, so the tool call proceeds unchanged. Scope: Claude Code sends no main-thread marker, so a
missing `agent_type` cannot be told apart from a harness that never sends one —
every session is checked, and the warning names `agent_type` when the payload
carries it. Any unparseable input or internal error is silence with exit 0.

`POLL_LOOP_RE` is exported because the Task 1.6 prose lint reuses the pattern.
"""
from __future__ import annotations

import json
import re
import sys

import wait_budget

# An `until`/`while` header, its `do` STARTING a command, then a `sleep` inside the loop body.
# The `do(?!\s+not\b)` guard is what keeps prose honest: "…while it prints `running`; do not
# sleep between polls" says the opposite of a loop, and the Task 1.6 prose lint reuses this pattern.
POLL_LOOP_RE = re.compile(
    r"\b(?:until|while)\b[^;\n]*(?:;|\n)\s*\bdo\b(?!\s+not\b)[\s\S]{0,200}?\bsleep\b")

_DOC = "skills/_shared/bg_wait.py"
_FIX = ("start it with run_in_background and wait through %s "
        "(<=%d s per call, inside the %d ms Bash budget)" % (
            _DOC, wait_budget.WAIT_BUDGET_S, wait_budget.BASH_TIMEOUT_MS))


def _warn(reason: str, agent_type: str | None) -> str:
    who = " in agent %s" % agent_type if agent_type else ""
    detail = "wait-ttl%s: %s" % (who, reason)
    return json.dumps({
        "systemMessage": detail + ". " + _FIX + ".",
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": detail + " — " + _FIX,
        }})


def _over_budget(timeout) -> bool:
    """True only for an int `timeout` strictly above the Bash budget the design sets."""
    return isinstance(timeout, int) and not isinstance(timeout, bool) and (
        timeout > wait_budget.BASH_TIMEOUT_MS)


def run(payload):
    """Return (stdout, exit_code) for one PreToolUse payload; "" means stay silent."""
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return "", 0
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict) or tool_input.get("run_in_background"):
        return "", 0
    agent_type = payload.get("agent_type")
    command = tool_input.get("command") or ""
    if _over_budget(tool_input.get("timeout")):
        return _warn("Bash timeout %s ms is over the %d ms cache budget" % (
            tool_input["timeout"], wait_budget.BASH_TIMEOUT_MS), agent_type), 0
    if POLL_LOOP_RE.search(command):
        return _warn("a foreground sleep-poll loop outlives the %d s cache TTL" % (
            wait_budget.CACHE_TTL_S), agent_type), 0
    return "", 0


def main():
    try:
        out, code = run(json.loads(sys.stdin.read()))
    except Exception:  # a hook that cannot read the payload must not touch the call
        out, code = "", 0
    if out:
        print(out)
    sys.exit(code)


if __name__ == "__main__":
    main()
