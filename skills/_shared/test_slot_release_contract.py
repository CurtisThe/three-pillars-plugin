"""test_slot_release_contract.py — three-pillars' lease shape vs the REAL router module.

design: slot-release-on-attempt-end (Task 1.5, Behaviors 4 + 6 + 7)

Every other lease test drives a fake ``slot_owner`` module, so this file is the one place that
checks the fakes are shaped like the router: ``SlotOwner.release_agent(endpoint, agent)`` really
is that signature, a hold taken through the router's OWN acquire path for a subagent is dropped
by ``local_lease.release_agent(<full id>)`` whether the router recorded it under the full id or
its id8, and the honest probe (Task 1.5) reads that same state — ``busy (slot held by agent
<id8>)`` while a foreign agent's hold is live, ``free`` once the release cleared it. It skips
when local-llm-skills is not installed (consumer repos: no router, no contract, no failure).
The state path is always a ``tmp_path`` file via ``$TP_LOCAL_SLOT_STATE`` — never the live
``~/.local/state`` slot the operator's conversations are using.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

import local_lease

# The unit-test fake whose shape this contract pins (test_local_lease_release.py).
from test_local_lease_release import _fake  # noqa: E402

EP = "http://127.0.0.1:11434"
ME = "5e55a0a1-mine-session"
AGENT = "a1b2c3d4-5e6f-7a8b-9c0d-1e2f3a4b5c6d"
FOREIGN = "9f8e7d6c-5b4a-3928-1706-5d4c3b2a1908"
FAKE_RELEASE_SIGNATURE = "(self, endpoint, agent)"


@pytest.fixture(name="router")
def _router(tmp_path, monkeypatch):
    """The real router module, with every slot-state read/write pointed at a tmp file.

    Skips when the install is absent: the consumer-repo contract is a clean no-op there. The
    suite-wide ``TP_SLOT_RELEASE=0`` switch is dropped for this module only — the state is a
    tmp file, so a release here cannot reach an operator's live hold.
    """
    module = local_lease.slot_owner_module()
    if module is None:
        pytest.skip("local-llm-skills router not installed")
    monkeypatch.delenv("TP_SLOT_RELEASE", raising=False)
    monkeypatch.setenv("TP_LOCAL_SLOT_STATE", str(tmp_path / "slot-owner.json"))
    return module


def _env(session=ME):
    """The in-process env the lease reads: a session whose id8 the router logs as the owner."""
    return {"CLAUDE_CODE_SESSION_ID": session}


def _take_hold(module, agent):
    """A subagent hold through the router's own acquire path, then released (in flight cleared).

    That is the state a finished local agent leaves: ``owner_agent`` / ``agent_seen`` set, the
    session still the owner, nothing in flight — exactly what the probe must read honestly.
    """
    owner = module.SlotOwner(one_agent=True)
    token, why = owner.acquire(EP, ME, subagent=True, agent=agent)
    assert token is not None, why
    owner.release(token)
    return owner.state_path


def _state(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_the_real_release_agent_signature_matches_the_fake(router):
    """The fake in ``test_local_lease_release.py`` may not invent a router API."""
    real = inspect.signature(router.SlotOwner.release_agent)
    fake = inspect.signature(_fake(Path("unused-slot-owner.json"))[0].SlotOwner.release_agent)
    assert str(real) == FAKE_RELEASE_SIGNATURE
    assert str(fake) == str(real)


@pytest.mark.parametrize("hold", [AGENT, AGENT[:8]])
def test_releasing_a_finished_agent_holds_nothing(router, hold):
    """Full id and id8 are the same agent to the router (`_same_agent` prefix-matches)."""
    state_path = _take_hold(router, hold)
    assert _state(state_path)[EP]["owner_agent"] == hold

    res = local_lease.release_agent(AGENT, env=_env(), module=router)
    assert res["outcome"] == "released", res
    slot = _state(state_path)[EP]
    assert slot["owner_agent"] is None and slot["agent_seen"] is None
    assert any(str(a).startswith(AGENT[:8]) for a in slot["released"])  # never sticky again
    assert local_lease.acquire(env=_env(), module=router) == ("free", "held by this session")


def test_a_foreign_agent_live_hold_makes_the_probe_busy(router):
    """Behavior 6 against the real state shape: this session owns the slot, an agent holds it."""
    _take_hold(router, FOREIGN)
    state, why = local_lease.acquire(env=_env(), module=router)
    assert (state, why) == ("busy", f"slot held by agent {FOREIGN[:8]}"), why


def test_the_main_thread_never_holds_the_slot_from_this_session(router):
    """The router's own exception: after a main-thread turn a sibling is not held off."""
    _take_hold(router, "main")
    assert local_lease.acquire(env=_env(), module=router) == ("free", "held by this session")


def test_the_probe_read_never_touches_the_live_state_path(router, tmp_path):
    """The contract runs on a tmp file: the operator's live slot state is not opened."""
    state_path = _take_hold(router, AGENT)
    assert Path(state_path).is_relative_to(tmp_path)
    local_lease.acquire(env=_env(), module=router)
    local_lease.release_agent(AGENT, env=_env(), module=router)
    assert Path(state_path).parent == tmp_path
    assert list(tmp_path.glob("slot-owner*"))
