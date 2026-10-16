"""router_busy_policy.py — tell the local router this run's busy policy.

design: wait-mode-router-leak (just-do-it, operator 2026-10-09)

``wait`` (``TP_LOCAL_MODE`` wait/exclusive, or ``strata_spawn.busy: wait``) means a busy GPU
makes the task wait, never run on Sonnet. The lease (``local_lease.acquire_timed``, run before
every local spawn) honours it, but the router decides each request on its own: a local request
it cannot admit (the slot taken by another conversation after the lease said free, the proxy
refusing) used to go upstream as its fallback model. The router is a long-lived service and
never sees the run's env, so the lease records the run's effective policy here, in
``busy-policy.json`` beside the router's ``slot-owner.json``, keyed by
``$CLAUDE_CODE_SESSION_ID`` — the ``x-claude-code-session-id`` every request of the run carries,
nested spawns included. The router (local-llm-skills ``bin/busy_policy.py``) reads it on a
refused local request: ``wait`` → hold, then 529 (Claude Code retries); else today's fallback.

    {"<session id>": {"policy": "wait" | "fallback", "at": <epoch s>}}

Every lease call rewrites its entry (``at`` refreshed); entries older than ``TTL_S`` are pruned
(the router ignores them too). Never raises: a failed write leaves the router on fallback.
Stdlib only.
"""
from __future__ import annotations

import fcntl
import json
import os
import time
from typing import Mapping

FILENAME = "busy-policy.json"
LOCK_NAME = "busy-policy.lock"
TTL_S = 6 * 3600.0  # the router's own default (bin/busy_policy.py TTL_S)
LOCK_BUDGET_S, LOCK_STEP_S = 1.0, 0.02
POLICIES = ("fallback", "wait")


def policy_from_env(env: Mapping[str, str]) -> str:
    """``TP_LOCAL_MODE`` as ``cheap_engine.local_mode`` reads it: wait/exclusive → ``wait``, else
    ``fallback``. Kept local (cheap_engine imports the ladder, which imports the lease)."""
    return "wait" if (env.get("TP_LOCAL_MODE") or "") in ("wait", "exclusive") else "fallback"


def path_for(state_path: str) -> str:
    """``busy-policy.json`` beside the router's slot state file."""
    return os.path.join(os.path.dirname(state_path), FILENAME)


def _load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def record(state_path: str, session: str | None, policy: str, *, clock=time.time,
           sleep=time.sleep) -> bool:
    """Write ``session``'s policy beside ``state_path``. -> True when written. Never raises."""
    if not session or policy not in POLICIES:
        return False
    try:
        path = path_for(state_path)
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        fd = os.open(os.path.join(os.path.dirname(path), LOCK_NAME), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            deadline = time.monotonic() + LOCK_BUDGET_S
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        return False
                    sleep(LOCK_STEP_S)
            now = clock()
            data = {k: v for k, v in _load(path).items()
                    if isinstance(v, dict) and isinstance(v.get("at"), (int, float))
                    and now - v["at"] < TTL_S}
            data[session] = {"policy": policy, "at": now}
            tmp = f"{path}.{os.getpid()}.tmp"
            with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as fh:
                json.dump(data, fh)
            os.replace(tmp, path)
            return True
        finally:
            os.close(fd)
    except Exception:  # noqa: BLE001 — never block a spawn on the policy note
        return False
