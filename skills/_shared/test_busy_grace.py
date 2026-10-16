"""test_busy_grace.py — the 3 s busy grace under the fallback policy.

design: one-cheap-engine (task 3.7). A fake lease records `wait_s`; no live router.
"""
from __future__ import annotations

import sys
from pathlib import Path

_DIR = Path(__file__).resolve().parent
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

import local_lease  # noqa: E402
import strata_spawn  # noqa: E402


class FakeLease:
    POLL_S = local_lease.POLL_S

    def __init__(self, held_for=None, state="busy"):
        self.held_for, self.state, self.calls = held_for, state, []

    def acquire_timed(self, **kw):
        self.calls.append(kw)
        wait_s = kw["wait_s"]
        if self.held_for is not None and wait_s >= self.held_for:
            return "free", "freed in grace", float(self.held_for)
        return self.state, "held", float(wait_s)


def _wait(lease, policy="fallback", **kw):
    return strata_spawn.wait(design="d", policy=policy, lease=lease,
                             clock=lambda: 0.0, sleep=lambda s: None, **kw), lease


def test_grace_is_three_seconds():
    assert strata_spawn.BUSY_GRACE_S == 3


def test_fallback_waits_grace_then_sonnet():
    (got, _why, _w), lease = _wait(FakeLease())
    assert got == "busy-fallback"
    assert lease.calls[0]["wait_s"] == strata_spawn.BUSY_GRACE_S


def test_slot_freed_inside_grace_is_free():
    (got, _why, _w), lease = _wait(FakeLease(held_for=2))
    assert got == "free"
    assert lease.calls[0]["wait_s"] == 3


def test_wait_policy_unchanged():
    (got, _why, _w), lease = _wait(FakeLease(), policy="wait", budget_s=300)
    assert got == "still-busy"
    assert lease.calls[0]["wait_s"] == 300
