"""lease_queue.py — the lease's side of the router's one waiter queue.

design: strata-fair-queue (Behaviors 1 and 10)

The router (local-llm-skills ``bin/slot_owner.py``) keeps the only FIFO of waiters, in its own
state file. Under the ``wait`` busy policy the lease's probe joins it: it asks with this
session's key (``$CLAUDE_CODE_SESSION_ID``, the conversation key every request of the run
carries) and ``waiter=True``, still ``subagent=False``, so the probe never takes the slot and is
answered ``agent-queued <pos>`` while another conversation holds it. The ``fallback`` policy,
no session id, or a router without ``SlotOwner.queue_view`` and an ``acquire`` that takes
``waiter`` keep today's probe (``tp-lease-probe``, ``subagent=False``). The lease writes no
queue of its own; this module only reads the router's (``queue_view``).

    supports(owner) -> bool                       the router's fair-queue API is there
    probe_args(owner, env, policy) -> (key, kw)   the probe's ``acquire`` key and keywords
    position(owner, ep, session) -> {position, total, waited_s} | None
    answer(owner, ep, why, session) -> ("busy", "queued <pos> of <n>", info) | None
    notify(on_poll, state, why, info)             the caller's per-probe callback
    fmt_wait(seconds) -> "XmYs"                   a wait as ``strata_spawn wait`` prints it

Never raises: anything unexpected reads as "no queue", which is today's lease. Stdlib only.
"""
from __future__ import annotations

import inspect
from typing import Mapping

PROBE_KEY = "tp-lease-probe"
WAIT_POLICY = "wait"
QUEUED = "agent-queued "


def supports(owner) -> bool:
    """The router's ``SlotOwner`` has ``queue_view`` and an ``acquire`` taking ``waiter``."""
    try:
        if not callable(getattr(owner, "queue_view", None)):
            return False
        return "waiter" in inspect.signature(owner.acquire).parameters
    except Exception:  # noqa: BLE001 — an uninspectable owner is an older router
        return False


def probe_args(owner, env: Mapping[str, str], policy: str | None) -> tuple[str, dict]:
    """``(key, keywords)`` for the probe's ``owner.acquire``: the session key as a waiter under
    ``wait`` with a session id and a router that queues, else today's side-traffic probe."""
    session = env.get("CLAUDE_CODE_SESSION_ID")
    if policy == WAIT_POLICY and session and supports(owner):
        return session, {"subagent": False, "waiter": True}
    return PROBE_KEY, {"subagent": False}


def _queued(why) -> int | None:
    """The position in an ``agent-queued <pos>`` answer, else ``None``."""
    if not isinstance(why, str) or not why.startswith(QUEUED):
        return None
    text = why[len(QUEUED):].strip()
    return int(text) if text.isdigit() and int(text) > 0 else None


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def position(owner, ep, session: str | None) -> dict | None:
    """``session``'s place in the router's queue for ``ep`` (``queue_view``, matched by id8):
    ``{position, total, waited_s}``, or ``None`` when not queued or unreadable. Never raises."""
    try:
        if not session or not callable(getattr(owner, "queue_view", None)):
            return None
        view = owner.queue_view(ep)
        queue = view.get("queue") if isinstance(view, dict) else None
        if not isinstance(queue, list):
            return None
        for entry in queue:
            if not isinstance(entry, dict) or entry.get("id8") != session[:8]:
                continue
            pos, waited = entry.get("position"), _number(entry.get("waited_s"))
            if isinstance(pos, int) and not isinstance(pos, bool) and pos > 0 \
                    and waited is not None:
                return {"position": pos, "total": len(queue), "waited_s": waited}
        return None
    except Exception:  # noqa: BLE001 — the read side never blocks a spawn
        return None


def answer(owner, ep, why, session: str | None) -> tuple[str, str, dict | None] | None:
    """An ``agent-queued <pos>`` probe answer as the lease's ``busy`` with
    ``queued <pos> of <n>`` and its queue read; ``None`` for any other answer."""
    pos = _queued(why)
    if pos is None:
        return None
    info = position(owner, ep, session)
    return "busy", f"queued {pos} of {max(pos, info['total']) if info else pos}", info


def notify(on_poll, state: str, why: str, info: dict | None) -> None:
    """``on_poll(state, why, info)`` after a probe; a failing callback never changes the
    lease's answer."""
    if on_poll is None:
        return
    try:
        on_poll(state, why, info)
    except Exception:  # noqa: BLE001 — progress output never blocks a spawn
        pass


def fmt_wait(seconds) -> str:
    """``XmYs`` for a wait in seconds (``250`` -> ``4m10s``); a bad value reads as 0."""
    try:
        total = max(int(round(float(seconds))), 0)
    except (TypeError, ValueError, OverflowError):
        total = 0
    return f"{total // 60}m{total % 60}s"
