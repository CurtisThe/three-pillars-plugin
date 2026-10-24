#!/usr/bin/env python3
"""context_rollover_wait.py - the waits and the refusal line of the context rollover.

design: fleet-watcher-reliability (Task 1.3; split out of `context_rollover_drive.py`,
moved verbatim). Four polls, each bounded by a deadline on the caller's clock, every
effect a seam: the pane's idle stretch (`_Idle`), the turn boundary (`_await_boundary`),
the post-`/clear` restore (`_await_restored`) and the handoff landing on disk
(`_await_commit`); plus `skipped_line`, the one line for a refused ledger claim.
"""
from __future__ import annotations

import os
import sys
from typing import Callable, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import context_rollover as cr  # noqa: E402
import context_rollover_state as state  # noqa: E402

__all__ = ["POLL_SECONDS", "STALE_GRACE_S", "_Idle", "_await_boundary", "_await_restored",
           "_await_commit", "skipped_line"]

POLL_SECONDS = 1.0
STALE_GRACE_S = 120.0  # a `claimed` entry older than save-timeout + this is a dead driver


class _Idle:
    """How long the pane has been unchanged, measured from the driver's own watching.

    The first sample only starts the clock, so an idle stretch is something the driver
    observes for itself rather than something it takes on trust from its caller.
    """

    def __init__(self, pane: Callable[[], Optional[str]], clock: Callable[[], float]):
        self.pane, self.clock = pane, clock
        self.text: object = object()
        self.since = clock()

    def idle_for_s(self) -> float:
        now = self.clock()
        text = self.pane()
        if text != self.text:
            self.text, self.since = text, now
        return now - self.since


def _await_boundary(idle: _Idle, records: Callable[[], "list[dict]"],
                    clock: Callable[[], float], sleep: Callable[[float], None],
                    idle_s: float, limit_s: float) -> "tuple[bool, str]":
    """Poll until the session is at a turn boundary, bounded by `limit_s`."""
    deadline = clock() + max(limit_s, idle_s)
    why = "no boundary observed"
    while True:
        ok, why = cr.at_turn_boundary(records(), idle.pane(), idle.idle_for_s(), idle_s)
        if ok:
            return True, ""
        if clock() >= deadline:
            return False, why
        sleep(POLL_SECONDS)


def _await_restored(old_sid: str, session: Callable[[], Optional[str]], idle: _Idle,
                    records: Callable[[], "list[dict]"], clock: Callable[[], float],
                    sleep: Callable[[float], None], idle_s: float, limit_s: float) -> bool:
    """Poll until a NEW session (post-/clear) has finished its restore turn."""
    deadline = clock() + max(limit_s, idle_s)
    while True:
        new = session()
        if new and new != old_sid and cr.at_turn_boundary(
                records(), idle.pane(), idle.idle_for_s(), idle_s)[0]:
            return True
        if clock() >= deadline:
            return False
        sleep(POLL_SECONDS)


def skipped_line(ledger, sid: str, now: float, save_timeout_s: float) -> str:
    """The one line for a refused claim, so a refusal is never silent.

    A `claimed` entry older than `save_timeout_s + STALE_GRACE_S` on the driver's clock
    (or stamped in the future: the clock restarted, so its driver is gone) is reported
    `stale-claimed` — a driver that was killed mid-rollover; clearing it is a human call.
    """
    found = state.entry(ledger, sid)
    if found is None:
        return (f"rollover skipped: session {sid} not claimable (ledger unreadable or "
                f"unwritable) (ledger {ledger})")
    what = found.get("state", "unknown")
    at = found.get("at")
    if what == state.CLAIMED and isinstance(at, (int, float)):
        age = now - at
        if age < 0 or age > save_timeout_s + STALE_GRACE_S:
            what = "stale-claimed"
    return f"rollover skipped: session {sid} already {what} (ledger {ledger})"


def _await_commit(handoff_sha: Callable[[], Optional[str]], before: Optional[str],
                  clock: Callable[[], float], sleep: Callable[[float], None],
                  timeout_s: float) -> bool:
    """True once `handoff.md` differs from `before` on disk — the save landed.

    A failed read is never a landed save: `HandoffUnreadable` propagates to the caller.
    """
    deadline = clock() + timeout_s
    while True:
        sha = handoff_sha()
        if sha is not None and sha != before:
            return True
        if clock() >= deadline:
            return False
        sleep(POLL_SECONDS)
