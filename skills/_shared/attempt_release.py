#!/usr/bin/env python3
"""attempt_release.py — release a finished local agent's slot hold once, and record it in W.

design: slot-release-on-attempt-end (Behaviors 1, 4). The watchdog's `poll` calls
`release_once` when an attempt reads `done`; the orphan path reuses it for a confirmed stop.
C1 holds: this never kills and never runs git — it only asks `local_lease.release_agent` to
drop the agent's router-state hold, then merges one `released: {at, outcome}` key into the
state file W. Fail-open: nothing here raises, and the verdict of the caller is never changed.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import local_lease  # noqa: E402


def release_outcome(agent_id) -> str:
    """The default release seam: the outcome string of `local_lease.release_agent`."""
    return local_lease.release_agent(agent_id)["outcome"]


def call_release(release, agent_id) -> str:
    """One seam call, error-wrapped: a raise becomes `"error: <msg>"`. Never raises."""
    try:
        return release(agent_id)
    except Exception as exc:  # noqa: BLE001 - a release failure never breaks its caller
        return f"error: {exc}"


def release_once(state_path, state: dict, *, release, read_json, write_json, clock) -> str:
    """Release `state["agent_id"]` once; return the outcome, or `"already"` if W records one.

    `release(agent_id) -> str` is the seam; a raise becomes `"error: <msg>"`. After the call W
    is re-read, and `released` is merged in only if its `agent_id` still matches — a W re-armed
    for a new agent in between keeps the new agent's state. Never raises.
    """
    if state.get("released"):
        return "already"
    agent_id = state.get("agent_id")
    outcome = call_release(release, agent_id)
    try:
        fresh = read_json(state_path)
        if fresh.get("agent_id") == agent_id and not fresh.get("released"):
            fresh["released"] = {"at": clock(), "outcome": outcome}
            write_json(state_path, fresh)
    except (OSError, ValueError, AttributeError):
        pass
    return outcome
