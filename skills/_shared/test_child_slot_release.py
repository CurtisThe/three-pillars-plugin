"""test_child_slot_release.py — releasing the inner agent's hold and the child session's.

design: strata-session-isolation (task 2.5)

``child_slot.release(inner_id, child)`` ends a child session's claim on the router: first
``local_lease.release_agent(inner_id)`` (the finished inner agent's sticky hold, reused as
is), then the router's ``SlotOwner.release_session(endpoint, child)`` once per key in the
slot state file. A child SIGKILLed mid-request leaves an in-flight entry the release cannot
get past, so a not-owner answer runs one side-traffic probe
``SlotOwner().acquire(ep, child, subagent=False)`` per key (the router's own reaper) and
retries the release once. Every failure — a router predating ``release_session``, a key
owned by another session, a missing state file, a raising call — answers from the closed
set ``released | not-owner | unsupported | error: …`` and never raises.

Every test drives a fake ``slot_owner`` module (the ``test_local_lease*.py`` stub pattern)
whose state file is under ``tmp_path``; nothing here reads or writes the live router state.
Because ``release_agent`` and the session pass each construct their OWN ``SlotOwner``, the
fake keeps its state and its call log on one shared closure object, not per instance.
test-fragility.md: assertions are on the recorded call order/keys and the returned dict,
never on message wording beyond ``error:`` naming the cause.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import child_slot  # noqa: E402

AGENT = "agent-1"
CHILD = "child-1"
OTHER = "other-session-9"
EP1, EP2 = "ep1", "ep2"
DEAD = "4242:1:child-1"  # the router's in-flight entry form: <pid>:<n>:<agent>


@pytest.fixture(autouse=True)
def _release_enabled(monkeypatch):
    """Opt this module back in: the suite-wide conftest fixture disables releases."""
    monkeypatch.delenv("TP_SLOT_RELEASE", raising=False)


def _state(tmp_path, *keys) -> Path:
    """A fixture slot-state file whose keys are the endpoints."""
    path = tmp_path / "slot-state.json"
    path.write_text(json.dumps({key: {} for key in keys}), encoding="utf-8")
    return path


# The three router methods the release path may call. Each one records its call on the
# shared _Router (module-level so the names are not class-local) and answers from it.
def _release_agent(self, endpoint, agent):
    self._shared.calls.append(("release_agent", endpoint, agent))
    return self._shared.agent_holders.get(endpoint) == agent


def _release_session(self, endpoint, key):
    self._shared.calls.append(("release_session", endpoint, key))
    if self._shared.release_error:
        raise RuntimeError(self._shared.release_error)
    # The router's rule: the key's own hold releases, but entries still in flight do not.
    return (self._shared.session_owners.get(endpoint) == key
            and not self._shared.in_flight.get(endpoint))


def _acquire(self, endpoint, key, subagent=True):
    self._shared.calls.append(("acquire", endpoint, key, subagent))
    # The router's own reaper: a dead child's in-flight entry goes, so its hold becomes
    # releasable. Only the entries the fixture marked dead — a live one stays.
    self._shared.in_flight[endpoint] = [
        e for e in self._shared.in_flight.get(endpoint, []) if e not in self._shared.dead]
    return self._shared.session_owners.get(endpoint) == key


class _Router:
    """The one shared state behind every ``SlotOwner`` a fake module constructs."""

    def __init__(self, state_path, agent_holders=None, session_owners=None, in_flight=None,
                 dead=(), release_error=None):
        self.state_path = state_path
        self.agent_holders = dict(agent_holders or {})
        self.session_owners = dict(session_owners or {})
        self.in_flight = {k: list(v) for k, v in (in_flight or {}).items()}
        self.dead = set(dead or ())
        self.release_error = release_error
        self.calls: list[tuple] = []

    def module(self, *, methods=("release_agent", "release_session", "acquire")):
        """A fake ``slot_owner`` module: its ``SlotOwner`` names the fixture state path and
        carries only ``methods`` — a router predating ``release_session`` omits it."""
        def __init__(self):
            self.state_path = str(self._shared.state_path)

        body = {"_shared": self, "__init__": __init__}
        for name in methods:
            body[name] = {"release_agent": _release_agent,
                          "release_session": _release_session,
                          "acquire": _acquire}[name]
        return types.SimpleNamespace(SlotOwner=type("Owner", (), body))


def _fake(tmp_path, *keys, agent_holders=None, session_owners=None, in_flight=None,
          dead=(), release_error=None) -> tuple[types.SimpleNamespace, _Router]:
    """``(module, router)``: the fake module plus the shared object the assertions read."""
    router = _Router(_state(tmp_path, *keys), agent_holders, session_owners, in_flight,
                     dead, release_error)
    return router.module(), router


def _names(router: _Router, kind: str) -> list[str]:
    """The endpoints ``kind`` was called for, in call order."""
    return [call[1] for call in router.calls if call[0] == kind]


def test_release_order_and_keys(tmp_path):
    """The agent goes first, then one ``release_session`` per key, in state-file order."""
    module, router = _fake(tmp_path, EP1, EP2, agent_holders={EP1: AGENT, EP2: AGENT},
                           session_owners={EP1: CHILD, EP2: CHILD})
    assert child_slot.release(AGENT, CHILD, module=module) == {
        "agent": "released", "session": "released"}
    assert router.calls == [("release_agent", EP1, AGENT), ("release_agent", EP2, AGENT),
                            ("release_session", EP1, CHILD), ("release_session", EP2, CHILD)]


def test_not_owner_then_probe_then_released(tmp_path):
    """Not-owner once: one probe per key (the router's reaper for a just-SIGKILLed child —
    never a polling loop), then one retry, which lands."""
    module, router = _fake(tmp_path, EP1, EP2, session_owners={EP1: CHILD, EP2: CHILD},
                           in_flight={EP1: [DEAD], EP2: [DEAD]}, dead={DEAD})
    res = child_slot.release(AGENT, CHILD, module=module)
    assert res["session"] == "released"
    assert res["agent"] == "not-holder"
    assert [c for c in router.calls if c[0] == "acquire"] == [
        ("acquire", EP1, CHILD, False), ("acquire", EP2, CHILD, False)]
    assert _names(router, "release_session") == [EP1, EP2, EP1, EP2]


def test_other_session_owns(tmp_path):
    """A key held by another session is left alone: one probe per key, one retry, then
    ``not-owner`` — no raise, and nothing of theirs is released."""
    module, router = _fake(tmp_path, EP1, EP2, session_owners={EP1: OTHER, EP2: OTHER})
    assert child_slot.release(AGENT, CHILD, module=module)["session"] == "not-owner"
    assert _names(router, "acquire") == [EP1, EP2]
    assert _names(router, "release_session") == [EP1, EP2, EP1, EP2]
    assert router.session_owners == {EP1: OTHER, EP2: OTHER}


def test_missing_method_unsupported(tmp_path):
    """A router install predating ``release_session``: the session side answers
    ``unsupported``, the agent side still works, and nothing raises."""
    router = _Router(_state(tmp_path, EP1), {EP1: AGENT})
    assert child_slot.release(AGENT, CHILD, module=router.module(
        methods=("release_agent",))) == {"agent": "released", "session": "unsupported"}


def test_exception_is_error_outcome(tmp_path):
    """A raising ``release_session`` (a lost state lock) is an outcome naming the cause,
    never an exception, and no probe is spent after it."""
    module, router = _fake(tmp_path, EP1, EP2, session_owners={EP1: CHILD},
                           release_error="slot lock timeout")
    res = child_slot.release(AGENT, CHILD, module=module)
    assert res["session"].startswith("error:") and "slot lock timeout" in res["session"]
    assert _names(router, "acquire") == []


def test_no_state_file_is_not_owner(tmp_path):
    """No slot state file at all: nothing to release, no router calls at all,
    ``not-owner``, no raise."""
    router = _Router(tmp_path / "absent-slot-state.json")
    assert child_slot.release(AGENT, CHILD, module=router.module())["session"] == "not-owner"
    assert router.calls == []


def test_agent_not_holder_passthrough(tmp_path):
    """The agent outcome is ``release_agent``'s own, passed through; the session release is
    attempted regardless of it."""
    module, router = _fake(tmp_path, EP1, EP2, agent_holders={EP1: OTHER, EP2: OTHER},
                           session_owners={EP1: CHILD, EP2: CHILD})
    res = child_slot.release(AGENT, CHILD, module=module)
    assert res["agent"] == "not-holder"
    assert res["session"] == "released"
    assert _names(router, "release_session") == [EP1, EP2]
