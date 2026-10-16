"""test_local_lease_agent_hold.py — the honest probe: a live agent hold is busy (Behavior 6).

design: slot-release-on-attempt-end (Task 1.5, Behavior 6 + 7)

The router's side-traffic probe answers per SESSION, so while this session owns the slot and
one of its agents is still in flight, or still sticky (`owner_agent`, not in `released`,
`agent_seen` within the router's `IDLE_S`), the probe says "slot held by <this session>" and
``acquire`` used to report ``free`` — the next spawn then went out and was answered
``agent-busy`` upstream as Sonnet. The probe now reads the agent holder too: that case is
``busy (slot held by agent <id8>)``, exit 3, so a ``--design`` window owner waits instead of
spawning into a fallback. A released or idle-expired hold with nothing in flight, ``main``, or
no holder keeps today's answer, and any read failure keeps it: the probe never raises and never
newly blocks a spawn. Every fake here is a module object over a fixture state file — nothing in
this file reads or writes the live router state.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

import local_lease

SCRIPT = Path(__file__).resolve().parent / "local_lease.py"
EP, EP2 = "http://127.0.0.1:11434", "http://127.0.0.1:8000"
ME, OTHER = "5e55a0a1-mine-session", "0b0e0b0e-other-session"
AGENT = "a1b2c3d4-5e6f-7a8b-9c0d-1e2f3a4b5c6d"
IDLE_S = 120.0
BUSY_AGENT = f"slot held by agent {AGENT[:8]}"
FREE_MINE = ("free", "held by this session")


@pytest.fixture(autouse=True)
def _no_live_measure_window(monkeypatch):
    """An operator's live measurement window must not answer these probes (``busy-measure``)."""
    monkeypatch.setattr(local_lease.measure_window, "load", lambda env: None)


def _env(session=ME):
    return {"CLAUDE_CODE_SESSION_ID": session}


def _slot(owner_key=ME, *, agent=AGENT, agent_seen_ago=5.0, released=(), in_flight=None,
          last_seen_ago=5.0):
    """One slot shaped like the router's state (``slot_owner.py``'s STATE section)."""
    now = time.time()
    return {"owner_key": owner_key, "in_flight": dict(in_flight or {}),
            "last_seen": now - last_seen_ago, "owner_agent": agent,
            "agent_seen": None if agent_seen_ago is None else now - agent_seen_ago,
            "released": {a: now - 1.0 for a in released}}


class _Owner:
    """``SlotOwner`` as the router documents it for side traffic: ``unowned`` when the slot is
    free (no owner, or idle past ``idle_s`` with nothing in flight), else ``slot held by <id8>``.
    It never takes the slot, and it names no agent — the holder is only in the state file."""

    def __init__(self, state_path, idle_s):
        self.state_path, self.idle_s, self.probes = str(state_path), idle_s, 0

    def acquire(self, endpoint, key, *, subagent):
        assert subagent is False and key, "the lease probe is side traffic, never a taker"
        self.probes += 1
        slot = json.loads(Path(self.state_path).read_text(encoding="utf-8")).get(endpoint) or {}
        held = slot.get("owner_key") is not None and (
            bool(slot.get("in_flight"))
            or time.time() - (slot.get("last_seen") or 0.0) < self.idle_s)
        if held:
            return None, f"slot held by {(slot.get('owner_key') or '')[:8]}"
        return (endpoint, None), "unowned"


def _module(tmp_path, slots, *, idle_s=IDLE_S, no_module_idle=False):
    """A fake router module over a fixture state file holding ``slots``: ``SlotOwner`` answers
    the session probe from it, ``IDLE_S`` is the module's window (``no_module_idle`` stands in
    for a router that never exported one). -> ``(module, state_path)``."""
    state_path = tmp_path / "slot-owner.json"
    state_path.write_text(json.dumps(slots), encoding="utf-8")
    ns = {"SlotOwner": lambda: _Owner(state_path, idle_s)}
    if not no_module_idle:
        ns["IDLE_S"] = idle_s
    return types.SimpleNamespace(**ns), state_path


# --------------------------------------------------------------------------- (a) the fake
@pytest.mark.parametrize("hold", [AGENT, AGENT[:8]])
def test_a_live_agent_hold_of_this_session_reads_busy(tmp_path, hold):
    """The Red: the session probe names THIS session, and one of its agents still holds it."""
    mod, _ = _module(tmp_path, {EP: _slot(agent=hold)})
    state, why = local_lease.acquire(env=_env(), module=mod)
    assert (state, why) == ("busy", BUSY_AGENT), why


def test_endpoint_limits_both_reads(tmp_path):
    """``--endpoint`` scopes the agent read too: another key's live hold is not this probe's."""
    mod, _ = _module(tmp_path, {EP: _slot(), EP2: _slot(owner_key=OTHER, last_seen_ago=900.0)})
    assert local_lease.acquire(EP2, env=_env(), module=mod) == ("free", "unowned")
    assert local_lease.acquire(EP, env=_env(), module=mod) == ("busy", BUSY_AGENT)


@pytest.mark.parametrize("done", [AGENT, AGENT[:8]])
def test_a_released_agent_hold_reads_free(tmp_path, done):
    """Task 1.1/1.2 did its job (or the router's TTL aged it out): the slot is free again."""
    mod, _ = _module(tmp_path, {EP: _slot(released=(done,))})
    assert local_lease.acquire(env=_env(), module=mod) == FREE_MINE


def test_an_idle_expired_agent_hold_reads_free(tmp_path):
    """Past the router's window the hold is the 120 s backstop's, not a live one."""
    mod, _ = _module(tmp_path, {EP: _slot(agent_seen_ago=IDLE_S + 30)})
    assert local_lease.acquire(env=_env(), module=mod) == FREE_MINE


@pytest.mark.parametrize("agent", ["main", None])
def test_no_agent_holder_or_main_keeps_todays_answer(tmp_path, agent):
    """Only a subagent hold counts — the main thread is never held off (Behavior 6)."""
    mod, _ = _module(tmp_path, {EP: _slot(agent=agent)})
    assert local_lease.acquire(env=_env(), module=mod) == FREE_MINE


def test_a_foreign_session_still_names_that_session(tmp_path):
    """Another conversation's hold is unchanged: its id8, no ``agent`` in the reason."""
    mod, _ = _module(tmp_path, {EP: _slot(owner_key=OTHER, agent=AGENT)})
    assert local_lease.acquire(env=_env(), module=mod) == ("busy", f"slot held by {OTHER[:8]}")


FLYING = "9f8e7d6c-5b4a-3928-1706-5d4c3b2a1908"


@pytest.mark.parametrize("sticky", [
    {"agent": None},                                  # no sticky holder at all
    {"agent": FLYING, "released": (FLYING,)},         # a stopped runaway, stream still open
    {"agent": FLYING, "agent_seen_ago": None},        # its first request: seen only on close
    {"agent": FLYING, "agent_seen_ago": IDLE_S + 30},  # seen long ago, next request open
])
def test_an_agent_in_flight_is_the_agent_holder(tmp_path, sticky):
    """The router's ``_agent_busy`` checks ``in_flight`` first: any other agent of this session
    in flight makes the next spawn ``agent-busy``, whatever the sticky pair says."""
    inflight = {f"{os.getpid()}:1:{FLYING}": time.time()}
    mod, _ = _module(tmp_path, {EP: _slot(in_flight=inflight, **sticky)})
    assert local_lease.acquire(env=_env(), module=mod) == (
        "busy", f"slot held by agent {FLYING[:8]}")


@pytest.mark.parametrize("entry", ["4242:1:main", "4242:1", "junk"])
def test_main_or_an_agentless_in_flight_entry_keeps_todays_answer(tmp_path, entry):
    """``main`` is the dispatcher itself, and an entry naming no agent names no holder."""
    mod, _ = _module(tmp_path, {EP: _slot(agent=None, in_flight={entry: time.time()})})
    assert local_lease.acquire(env=_env(), module=mod) == FREE_MINE


@pytest.mark.parametrize("broken", [
    {"agent_seen": "yesterday"},            # not a number
    {"owner_agent": {"id": AGENT}},         # not a string
    {"agent_seen": 0.0, "released": "no-mapping"},  # the released read fails
])
def test_a_malformed_agent_field_keeps_todays_answer(tmp_path, broken):
    """State written by another router version: the read fails, today's answer survives."""
    mod, _ = _module(tmp_path, {EP: {**_slot(), **broken}})
    assert local_lease.acquire(env=_env(), module=mod) == FREE_MINE


def test_the_idle_window_is_the_router_module_s(tmp_path):
    """The router's own ``IDLE_S`` decides: past it the hold is expired, inside it is live."""
    mod, _ = _module(tmp_path, {EP: _slot(agent_seen_ago=45.0)}, idle_s=30.0)
    assert local_lease.acquire(env=_env(), module=mod) == FREE_MINE
    mod, _ = _module(tmp_path, {EP: _slot(agent_seen_ago=45.0)}, idle_s=60.0)
    assert local_lease.acquire(env=_env(), module=mod) == ("busy", BUSY_AGENT)


def test_a_module_without_idle_s_still_honours_a_live_hold(tmp_path):
    """An older router exports no ``IDLE_S``; the probe's own window still answers busy."""
    mod, _ = _module(tmp_path, {EP: _slot(agent_seen_ago=45.0)}, no_module_idle=True)
    assert local_lease.acquire(env=_env(), module=mod) == ("busy", BUSY_AGENT)


def test_a_window_owner_waits_for_the_agent_hold(tmp_path):
    """Behavior 6's point: the owner waits rather than spawning into an agent-busy fallback."""
    class _Clock:
        def __init__(self):
            self.now, self.sleeps = 1000.0, []

        def __call__(self):
            return self.now

        def sleep(self, seconds):
            self.sleeps.append(seconds)
            self.now += seconds

    mod, state_path = _module(tmp_path, {EP: _slot()})
    clock = _Clock()
    state, why, waited = local_lease.acquire_timed(EP, env=_env(), module=mod, design="D",
                                                   wait_s=30, clock=clock, sleep=clock.sleep)
    assert (state, why) == ("busy", BUSY_AGENT)
    assert waited > 0 and clock.sleeps

    state_path.write_text(json.dumps({EP: _slot(released=(AGENT,))}), encoding="utf-8")
    state, why, _ = local_lease.acquire_timed(EP, env=_env(), module=mod, design="D",
                                              wait_s=30, clock=clock, sleep=clock.sleep)
    assert (state, why) == FREE_MINE


def test_cli_busy_from_an_agent_hold_exits_3(tmp_path):
    """End to end: a fake ``tp-local`` whose sibling ``slot_owner.py`` carries agent fields."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    launcher = bin_dir / "tp-local"
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    launcher.chmod(0o755)
    state = tmp_path / "slot-owner.json"
    state.write_text(json.dumps({EP: _slot()}), encoding="utf-8")
    (bin_dir / "slot_owner.py").write_text(
        "import json\n"
        f"STATE = {str(state)!r}\n"
        "IDLE_S = 120.0\n"
        "class SlotOwner:\n"
        "    state_path = STATE\n"
        "    def acquire(self, ep, key, *, subagent):\n"
        "        assert subagent is False\n"
        "        return None, 'slot held by ' + json.load(open(STATE))[ep]['owner_key'][:8]\n",
        encoding="utf-8")
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
           "CLAUDE_CODE_SESSION_ID": ME}
    res = subprocess.run([sys.executable, str(SCRIPT), "acquire"], capture_output=True,
                         text=True, env=env, timeout=30)
    assert (res.returncode, res.stdout.strip()) == (3, f"lease: busy ({BUSY_AGENT})")
