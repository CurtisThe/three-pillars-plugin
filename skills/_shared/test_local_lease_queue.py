"""test_local_lease_queue.py — the lease joins and reads the router's one queue.

design: strata-fair-queue (Task 1.5, Behaviors 1 and 10)

Under the ``wait`` busy policy, against a router whose ``SlotOwner`` has ``queue_view`` and an
``acquire`` that takes ``waiter``, the lease's probe asks with this session's key and
``waiter=True`` (still ``subagent=False``: it never takes the slot), so a run sitting in
``strata_spawn wait`` is queued by the router. ``agent-queued <pos>`` reads ``busy`` with
``queued <pos> of <n>``; the position comes from the router's ``queue_view``. The ``fallback``
policy, a missing session id or an older router keep today's ``tp-lease-probe`` probe. The lease
keeps no queue of its own. Stub routers over temp state files, plus one case against the real
``slot_owner.py`` (``TP_TEST_SLOT_OWNER_PY``, a temp ``TP_LOCAL_SLOT_STATE``): nothing here
touches the live router. test-fragility.md: assertions are on returned states, recorded call
arguments, parsed state JSON and the tokens a line names, never a whole message.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import time
import types
from pathlib import Path

import pytest

import local_lease
import router_busy_policy as rbp

REPO_ROOT = Path(__file__).resolve().parents[2]
EP = "http://127.0.0.1:3457"
ME, OTHER = "5e55a0a1-mine-session", "0b0e0b0e-other-session"
AGENT = "a1b2c3d4-5e6f-7a8b-9c0d-1e2f3a4b5c6d"
PROBE_KEY = "tp-lease-probe"
QUEUE = [{"id8": "77777777", "position": 1, "waited_s": 90.0},
         {"id8": ME[:8], "position": 2, "waited_s": 40.0},
         {"id8": "99999999", "position": 3, "waited_s": 5.0}]
UNSET = object()
TODAY = [(PROBE_KEY, {"subagent": False})]
WAITER = [(ME, {"subagent": False, "waiter": True})]


@pytest.fixture(autouse=True)
def _no_live_measure_window(monkeypatch):
    """An operator's live measurement window must not answer these probes (``busy-measure``)."""
    monkeypatch.setattr(local_lease.measure_window, "load", lambda env: None)


class _NewOwner:
    """A router with the fair queue. A waiter probe answers ``answers`` in turn (the last one
    repeating); any other probe sees the slot held by OTHER. Each probe's keywords are recorded."""

    def __init__(self, state_path, answers=("agent-queued 2",), queue=QUEUE):
        self.state_path, self.answers, self.queue = str(state_path), list(answers), queue
        self.calls = []

    def acquire(self, endpoint, key, *, subagent, waiter=UNSET, **extra):
        passed = {"subagent": subagent, **extra}
        if waiter is not UNSET:
            passed["waiter"] = waiter
        self.calls.append((key, passed))
        if waiter is not True:
            return None, f"slot held by {OTHER[:8]}"
        return None, self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]

    def queue_view(self, endpoint):
        return {"holder": OTHER[:8], "hold_age_s": 30.0, "turns": 1, "budget_left_s": 870.0,
                "queue": self.queue}

    def peek(self, endpoint):
        return False, OTHER[:8]


class _OldOwner:
    """A router before the fair queue: no ``queue_view``, an ``acquire`` without ``waiter``."""

    def __init__(self, state_path):
        self.state_path, self.calls = str(state_path), []

    def acquire(self, endpoint, key, *, subagent):
        self.calls.append((key, {"subagent": subagent}))
        return None, f"slot held by {OTHER[:8]}"


class _HalfOwner(_OldOwner):
    """``queue_view`` but an ``acquire`` that takes no ``waiter``: not the newer router."""

    def queue_view(self, endpoint):
        return {"queue": QUEUE}


def _state(tmp_path) -> Path:
    path = tmp_path / "state" / "slot-owner.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({EP: {"owner_key": OTHER, "in_flight": {},
                                     "last_seen": time.time()}}), encoding="utf-8")
    return path


def _module(owner):
    return types.SimpleNamespace(SlotOwner=lambda: owner)


def _timed(owner, policy, *, env=None, **kw):
    env = {"CLAUDE_CODE_SESSION_ID": ME} if env is None else env
    return local_lease.acquire_timed(EP, env=env, module=_module(owner), busy_policy=policy,
                                     wait_s=kw.pop("wait_s", 0), **kw)


def _files(root) -> set[str]:
    return {p.name for p in Path(root).rglob("*") if p.is_file()}


# --------------------------------------------------------------------------- the waiter probe
def test_wait_policy_probes_as_a_waiter_and_reads_its_position(tmp_path):
    owner = _NewOwner(_state(tmp_path))
    state, why, _waited = _timed(owner, "wait")
    assert state == "busy" and "queued 2 of 3" in why, why
    assert owner.calls == WAITER


def test_own_reserved_head_reads_free(tmp_path):
    """The slot reserved for this session's head answers ``slot held by <own id8>``."""
    owner = _NewOwner(_state(tmp_path), answers=(f"slot held by {ME[:8]}",))
    assert _timed(owner, "wait")[:2] == ("free", "held by this session")
    assert owner.calls == WAITER


@pytest.mark.parametrize("policy,env", [("fallback", {"CLAUDE_CODE_SESSION_ID": ME}),
                                        ("wait", {})])
def test_fallback_or_no_session_is_todays_probe(tmp_path, policy, env):
    owner = _NewOwner(_state(tmp_path))
    assert _timed(owner, policy, env=env)[:2] == ("busy", f"slot held by {OTHER[:8]}")
    assert owner.calls == TODAY


@pytest.mark.parametrize("cls", [_OldOwner, _HalfOwner])
def test_an_older_router_gets_todays_probe(tmp_path, cls):
    owner, polled = cls(_state(tmp_path)), []
    got = _timed(owner, "wait", on_poll=lambda *a: polled.append(a))
    assert got[:2] == ("busy", f"slot held by {OTHER[:8]}")
    assert owner.calls == TODAY
    assert polled == [("busy", f"slot held by {OTHER[:8]}", None)]


@pytest.mark.parametrize("flag,mode,want", [("wait", "", "wait"), ("fallback", "wait", "fallback"),
                                            (None, "wait", "wait"), (None, "exclusive", "wait")])
def test_the_waiter_flag_uses_the_policy_note_policy_resolved(tmp_path, flag, mode, want):
    owner = _NewOwner(_state(tmp_path))
    env = {"CLAUDE_CODE_SESSION_ID": ME, "TP_LOCAL_MODE": mode}
    assert local_lease._note_policy(env, _module(owner), shutil.which, flag) == want
    local_lease.acquire_timed(EP, env=env, module=_module(owner), busy_policy=flag, wait_s=0)
    recorded = json.loads(Path(rbp.path_for(owner.state_path)).read_text(encoding="utf-8"))
    assert recorded[ME]["policy"] == want
    assert owner.calls == (WAITER if want == "wait" else TODAY)


# --------------------------------------------------------------------------- the position read
def test_position_reads_the_router_queue_view(tmp_path):
    import lease_queue
    owner = _NewOwner(_state(tmp_path))
    assert lease_queue.position(owner, EP, ME) == {"position": 2, "total": 3, "waited_s": 40.0}


@pytest.mark.parametrize("owner,session", [
    (_NewOwner("x"), OTHER),                                   # not in the queue
    (_NewOwner("x"), None),                                    # no session id
    (_NewOwner("x", queue=[]), ME),                            # queue: []
    (_NewOwner("x", queue="junk"), ME),                        # not a list
    (_NewOwner("x", queue=[None, {"id8": ME[:8], "position": "2"}]), ME),  # malformed entries
    (types.SimpleNamespace(queue_view=lambda ep: None), ME),   # no view at all
    (types.SimpleNamespace(queue_view=lambda ep: 1 / 0), ME),  # a broken view
    (_OldOwner("x"), ME),                                      # an older router
])
def test_position_is_none_when_unknown_and_never_raises(owner, session):
    import lease_queue
    assert lease_queue.position(owner, EP, session) is None


def test_on_poll_gets_every_probe_with_its_queue_info(tmp_path):
    class _Clock:
        now = 1000.0

        def __call__(self):
            return self.now

        def sleep(self, seconds):
            self.now += seconds

    answers = ("agent-queued 2", "agent-queued 2", f"slot held by {ME[:8]}")
    owner, clock, polled = _NewOwner(_state(tmp_path), answers=answers), _Clock(), []
    got = _timed(owner, "wait", wait_s=60, clock=clock, sleep=clock.sleep,
                 on_poll=lambda *a: polled.append(a))
    assert got[:2] == ("free", "held by this session")
    assert [p[0] for p in polled] == ["busy", "busy", "free"] and len(owner.calls) == 3
    assert polled[0][2] == {"position": 2, "total": 3, "waited_s": 40.0}


# --------------------------------------------------------------------------- never raises
class _BrokenAcquire(_NewOwner):
    def acquire(self, endpoint, key, *, subagent, waiter=False):
        raise RuntimeError("router module broken")


class _BrokenView(_NewOwner):
    def queue_view(self, endpoint):
        raise RuntimeError("view broken")


def test_a_broken_router_module_is_unchecked(tmp_path):
    boom = types.SimpleNamespace(SlotOwner=lambda: (_ for _ in ()).throw(RuntimeError("x")))
    got = local_lease.acquire_timed(EP, env={"CLAUDE_CODE_SESSION_ID": ME}, module=boom,
                                    busy_policy="wait", wait_s=0)
    assert got[0] == "unchecked" and len(got) == 3
    assert _timed(_BrokenAcquire(_state(tmp_path)), "wait")[0] == "unchecked"


def test_a_broken_view_or_callback_keeps_the_queued_answer(tmp_path):
    polled = []
    state, why, _ = _timed(_BrokenView(_state(tmp_path)), "wait",
                           on_poll=lambda *a: polled.append(a))
    assert state == "busy" and "queued 2" in why and polled[0][2] is None

    def _raise(*_a):
        raise RuntimeError("callback broken")
    state, why, _ = _timed(_NewOwner(_state(tmp_path)), "wait", on_poll=_raise)
    assert state == "busy" and "queued 2 of 3" in why


def test_the_lease_keeps_no_queue_of_its_own(tmp_path):
    """One queue: the lease writes only the router's state and the busy-policy note."""
    state_path = _state(tmp_path)
    _timed(_NewOwner(state_path), "wait")
    assert _files(tmp_path) <= {state_path.name, rbp.FILENAME, rbp.LOCK_NAME}


# --------------------------------------------------------------------------- the real router
def _real_slot_owner(monkeypatch):
    """The Task 1.2 ``slot_owner.py``, loaded by file path (it appends its own dir to sys.path)."""
    path = REPO_ROOT / os.environ["TP_TEST_SLOT_OWNER_PY"]
    monkeypatch.setattr(sys, "path", list(sys.path))
    spec = importlib.util.spec_from_file_location("tp_test_real_slot_owner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _slot(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))[EP]


@pytest.mark.skipif(not os.environ.get("TP_TEST_SLOT_OWNER_PY"),
                    reason="TP_TEST_SLOT_OWNER_PY unset: no real slot_owner.py to load")
def test_real_slot_owner_queues_the_waiter_probe_and_never_grants_it(tmp_path, monkeypatch):
    module = _real_slot_owner(monkeypatch)
    for knob in ("TP_LOCAL_SLOT_QUANTUM_TURNS", "TP_LOCAL_SLOT_QUANTUM_S",
                 "TP_LOCAL_SLOT_HOLD_BUDGET_S", "TP_LOCAL_SLOT_HEAD_GRACE_S"):
        monkeypatch.delenv(knob, raising=False)
    env = {"CLAUDE_CODE_SESSION_ID": ME}

    held = tmp_path / "held" / "slot-owner.json"
    held.parent.mkdir()
    monkeypatch.setenv("TP_LOCAL_SLOT_STATE", str(held))
    token, why = module.SlotOwner(state_path=held).acquire(EP, OTHER, subagent=True, agent=AGENT)
    assert token is not None, why  # another session's subagent hold, in flight with a live pid
    seeded = dict(_slot(held)["in_flight"])
    state, why, _ = local_lease.acquire_timed(EP, env=env, module=module, busy_policy="wait",
                                              wait_s=0)
    assert state == "busy" and "queued 1 of 1" in why, why
    slot = _slot(held)
    assert [e["key"] for e in slot["queue"]] == [ME]
    assert slot["in_flight"] == seeded and slot["owner_key"] == OTHER
    lock = Path(module.SlotOwner().lock_path).name
    assert _files(held.parent) <= {held.name, lock, rbp.FILENAME, rbp.LOCK_NAME}

    free = tmp_path / "free" / "slot-owner.json"
    free.parent.mkdir()
    free.write_text(json.dumps({EP: {"owner_key": None, "in_flight": {}, "last_seen": None}}),
                    encoding="utf-8")
    monkeypatch.setenv("TP_LOCAL_SLOT_STATE", str(free))
    got = local_lease.acquire_timed(EP, env=env, module=module, busy_policy="wait", wait_s=0)
    assert got[:2] == ("free", "unowned")
    slot = _slot(free)
    assert not slot.get("queue") and slot["in_flight"] == {} and slot["owner_key"] is None
