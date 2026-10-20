"""test_strata_spawn_queue.py — `strata_spawn wait` prints the position and the total wait.

design: strata-fair-queue (Task 1.6, Behavior 9)

Under the ``wait`` busy policy, ``wait`` hands ``local_lease.acquire_timed`` an ``on_poll`` that
writes one stderr line per poll: ``queued``, the position, the total and an ``XmYs`` wait read
from the router's ``waited_s`` (design example ``strata_spawn: queued, position 2 of 3, waited
4m10s``). A poll with no queue info (an older router) prints the old ``busy (<why>)`` text. When
the slot is granted, the last line names the total wait since ``started_at``. The ``fallback``
policy prints no queue line, stdout stays the one JSON object, exit codes are unchanged, and an
``unrouted``/``unhealthy`` route never touches the lease. A lease whose ``acquire_timed`` takes
no ``on_poll`` still works. Every case injects a fake lease, clock and route check: no live
router. test-fragility.md: assertions are on returned states, recorded calls, parsed JSON and
the tokens a line names, never a whole message.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parent
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

import lease_queue  # noqa: E402
import local_lease  # noqa: E402
import local_route_check  # noqa: E402
import strata_spawn  # noqa: E402

Q2 = {"position": 2, "total": 3, "waited_s": 250.0}
Q1 = {"position": 1, "total": 3, "waited_s": 265.0}
QUEUED_POLLS = [("busy", "queued 2 of 3", Q2), ("busy", "queued 1 of 3", Q1)]


class FakeLease:
    """``acquire_timed`` calls ``on_poll`` with scripted ``(state, why, info)`` polls."""
    POLL_S = local_lease.POLL_S

    def __init__(self, polls=(), ret=("free", "unowned", 30.0)):
        self.polls, self.ret, self.calls = list(polls), ret, []

    def acquire_timed(self, *, design=None, wait_s=None, busy_policy=None, on_poll=None):
        self.calls.append({"design": design, "wait_s": wait_s, "busy_policy": busy_policy,
                           "on_poll": on_poll})
        for poll in self.polls:
            if on_poll is not None:
                on_poll(*poll)
        return self.ret


class OldLease:
    """A lease from before the fair queue: ``acquire_timed`` takes no ``on_poll``."""
    POLL_S = local_lease.POLL_S

    def __init__(self, ret=("free", "unowned", 0.0)):
        self.ret, self.calls = ret, 0

    def acquire_timed(self, *, design=None, wait_s=None, busy_policy=None):
        self.calls += 1
        return self.ret


def _err_lines(capsys):
    return [ln for ln in capsys.readouterr().err.splitlines() if ln.strip()]


def run(lease, policy="wait", *, started_at=1000.0, now=1362.0, **kw):
    return strata_spawn.wait(design="d", policy=policy, started_at=started_at, lease=lease,
                             clock=lambda: now, sleep=lambda s: None, **kw)


# --- formatting ---

@pytest.mark.parametrize("seconds", [250, 250.0])
def test_fmt_wait_is_minutes_and_seconds(seconds):
    assert lease_queue.fmt_wait(seconds) == "4m10s"


# --- each poll names queued, the position, the total and the router's wait ---

def test_each_poll_prints_one_queue_line(capsys):
    got = run(FakeLease(QUEUED_POLLS))
    assert got[0] == "free"
    queued = [ln for ln in _err_lines(capsys) if "position" in ln]
    assert len(queued) == 2
    first, second = queued
    for token in ("strata_spawn", "queued", "position 2", "of 3", "4m10s"):
        assert token in first
    for token in ("queued", "position 1", "of 3", lease_queue.fmt_wait(265.0)):
        assert token in second


def test_the_wait_policy_hands_the_lease_an_on_poll():
    lease = FakeLease()
    run(lease)
    assert callable(lease.calls[0]["on_poll"])


# --- the grant: the last line names the total wait since started_at ---

def test_grant_last_line_names_the_total_wait(capsys):
    run(FakeLease(QUEUED_POLLS), started_at=1000.0, now=1362.0)
    lines = _err_lines(capsys)
    assert lines, "no stderr line on the grant"
    last = lines[-1]
    assert lease_queue.fmt_wait(362) in last
    assert "position" not in last


def test_no_grant_line_while_still_busy(capsys):
    lease = FakeLease(QUEUED_POLLS, ret=("busy", "queued 1 of 3", 30.0))
    got = run(lease, started_at=1000.0, now=1362.0)
    assert got[0] == "still-busy"
    assert all(lease_queue.fmt_wait(362) not in ln for ln in _err_lines(capsys))


# --- no queue info (an older router): the old busy text ---

def test_poll_without_queue_info_prints_the_busy_line(capsys):
    lease = FakeLease([("busy", "slot held by abcd1234", None)])
    run(lease)
    lines = _err_lines(capsys)
    busy = [ln for ln in lines if "busy (" in ln]
    assert len(busy) == 1
    assert "busy (slot held by abcd1234)" in busy[0]
    assert all("position" not in ln for ln in lines)


# --- the output contract ---

def test_fallback_policy_prints_no_queue_line(capsys):
    got = run(FakeLease(QUEUED_POLLS, ret=("busy", "queued 1 of 3", 3.0)), policy="fallback")
    assert got[0] == "busy-fallback"
    err = capsys.readouterr().err
    assert "position" not in err and "queued" not in err


class FakeTime:
    def __init__(self, now=1362.0):
        self.now = now

    def time(self):
        return self.now

    def sleep(self, s):
        pass


@pytest.mark.parametrize("ret,code", [
    (("free", "unowned", 30.0), 0), (("busy", "queued 1 of 3", 30.0), 3)])
def test_cli_stdout_stays_one_json_object(monkeypatch, capsys, ret, code):
    monkeypatch.setattr(strata_spawn, "local_lease", FakeLease(QUEUED_POLLS, ret=ret))
    monkeypatch.setattr(strata_spawn, "time", FakeTime())
    got = strata_spawn.main(["wait", "--busy", "wait", "--started-at", "1000"])
    captured = capsys.readouterr()
    assert got == code
    lines = captured.out.strip().splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["state"] == ("free" if code == 0 else "still-busy")
    assert data["started_at"] == 1000.0
    assert "position 2" in captured.err


# --- a route that is not usable prints no queue line and never touches the lease ---

def _route(state, reason):
    return lambda: {"schema": local_route_check.SCHEMA, "state": state, "reason": reason,
                    "base_url": None, "checked_at": "x", "ollama": None, "detail": ""}


@pytest.mark.parametrize("state,reason,expect", [
    ("unrouted", "no-base-url", "unrouted"), ("router-down", "connect-refused", "unhealthy")])
def test_unusable_route_prints_no_queue_line(capsys, state, reason, expect):
    lease = FakeLease(QUEUED_POLLS)
    got = run(lease, route_check=_route(state, reason))
    assert got[0] == expect
    assert lease.calls == []
    err = capsys.readouterr().err
    assert "position" not in err and "queued" not in err and "busy (" not in err


# --- an old lease (no on_poll) still works ---

def test_a_lease_without_on_poll_still_works(capsys):
    lease = OldLease()
    got = run(lease)
    assert got[0] == "free" and lease.calls == 1
    assert "position" not in capsys.readouterr().err
