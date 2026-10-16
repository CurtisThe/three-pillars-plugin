"""test_local_lease_release.py — releasing a finished agent's router hold.

design: slot-release-on-attempt-end (Task 1.1, Behavior 4 + 7)

``local_lease.release_agent(agent_id)`` is the one place three-pillars drops a finished
local agent's hold on the router's GPU slot: the router's own
``SlotOwner.release_agent(endpoint, agent)`` once per key in its slot state file, the
full agent id passed unchanged (the router prefix-matches id8). Every failure mode — no
router, a router predating ``release_agent``, a missing state file, a raising call —
answers with a value from the closed outcome set and never raises. Every test here drives
a fake module: nothing in this file reads or writes the live router state.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

import local_lease

SCRIPT = Path(__file__).resolve().parent / "local_lease.py"
EP, EP2 = "http://127.0.0.1:11434", "http://127.0.0.1:8000"
AGENT = "a1b2c3d4-5e6f-7a8b-9c0d-1e2f3a4b5c6d"


@pytest.fixture(autouse=True)
def _release_enabled(monkeypatch):
    """Opt this module back in: the suite-wide conftest fixture disables releases."""
    monkeypatch.delenv("TP_SLOT_RELEASE", raising=False)


def _which(_name):
    """A router install exists; only the fake module behind it matters to these tests."""
    return "/fake-bin/tp-local"


def _state(tmp_path, *endpoints) -> Path:
    """A fixture slot-state file whose keys are the endpoints."""
    path = tmp_path / "slot-owner.json"
    path.write_text(json.dumps({ep: {"owner_key": AGENT[:8], "owner_agent": AGENT,
                                    "in_flight": {}, "last_seen": time.time()}
                                for ep in endpoints}), encoding="utf-8")
    return path


def _fake(state_path, *, holders=None, error=None, ctor_error=None):
    """A fake ``slot_owner`` module (the ``test_local_lease.py`` stub pattern).

    Returns ``(module, calls)``: its ``SlotOwner`` reads ``state_path``, records every
    ``(endpoint, agent)`` release in ``calls``, and returns True for an endpoint whose
    holder is that agent. ``error`` / ``ctor_error`` make the release / the constructor
    raise, as a lock timeout or an unreadable state would.
    """
    calls: list[tuple[str, str]] = []
    holders = holders or {}

    class Owner:
        def __init__(self):
            if ctor_error:
                raise RuntimeError(ctor_error)
            self.state_path = str(state_path)

        def release_agent(self, endpoint, agent):
            calls.append((endpoint, agent))
            if error:
                raise RuntimeError(error)
            return holders.get(endpoint) == agent

    return type("M", (), {"SlotOwner": Owner}), calls


def test_released_when_one_endpoint_releases_and_every_key_is_called(tmp_path):
    mod, calls = _fake(_state(tmp_path, EP, EP2), holders={EP2: AGENT})
    res = local_lease.release_agent(AGENT, module=mod, which=_which)
    assert res == {"outcome": "released", "endpoints": [EP, EP2]}
    assert calls == [(EP, AGENT), (EP2, AGENT)]  # the full id, unchanged, per key


def test_every_key_is_released_even_after_one_succeeds(tmp_path):
    mod, calls = _fake(_state(tmp_path, EP, EP2), holders={EP: AGENT})
    res = local_lease.release_agent(AGENT, module=mod, which=_which)
    assert res == {"outcome": "released", "endpoints": [EP, EP2]}
    assert calls == [(EP, AGENT), (EP2, AGENT)]


def test_not_holder_when_no_endpoint_releases(tmp_path):
    mod, calls = _fake(_state(tmp_path, EP, EP2), holders={EP: "0b0e0b0e-other-agent"})
    res = local_lease.release_agent(AGENT, module=mod, which=_which)
    assert res == {"outcome": "not-holder", "endpoints": [EP, EP2]}
    assert len(calls) == 2


def test_missing_state_file_is_not_holder_with_no_calls(tmp_path):
    mod, calls = _fake(tmp_path / "absent-slot-owner.json")
    res = local_lease.release_agent(AGENT, module=mod, which=_which)
    assert res == {"outcome": "not-holder", "endpoints": []}
    assert calls == []


def test_no_router_install_is_no_router():
    res = local_lease.release_agent(AGENT, which=lambda _name: None)
    assert res == {"outcome": "no-router", "endpoints": []}


def test_router_predating_release_agent_is_unsupported(tmp_path):
    state = _state(tmp_path, EP)

    class OldOwner:  # a SlotOwner with no ``release_agent`` at all
        def __init__(self):
            self.state_path = str(state)

    res = local_lease.release_agent(AGENT, module=type("M", (), {"SlotOwner": OldOwner}),
                                    which=_which)
    assert res == {"outcome": "unsupported", "endpoints": []}


def test_raising_release_agent_is_an_error_outcome_never_a_raise(tmp_path):
    mod, _ = _fake(_state(tmp_path, EP), error="slot lock timeout")
    res = local_lease.release_agent(AGENT, module=mod, which=_which)
    assert res["outcome"].startswith("error:") and "slot lock timeout" in res["outcome"]
    assert res["endpoints"] == []


def test_raising_slot_owner_constructor_is_an_error_outcome(tmp_path):
    mod, _ = _fake(_state(tmp_path, EP), ctor_error="slot state unreadable")
    res = local_lease.release_agent(AGENT, module=mod, which=_which)
    assert res["outcome"].startswith("error:") and "slot state unreadable" in res["outcome"]
    assert res["endpoints"] == []


@pytest.mark.parametrize("agent_id", ["", None])
def test_an_empty_agent_id_is_not_holder_with_no_calls(tmp_path, agent_id):
    mod, calls = _fake(_state(tmp_path, EP))
    res = local_lease.release_agent(agent_id, module=mod, which=_which)
    assert res == {"outcome": "not-holder", "endpoints": []}
    assert calls == []


def test_disabled_switch_answers_before_any_module_load(tmp_path, monkeypatch):
    monkeypatch.setenv("TP_SLOT_RELEASE", "0")
    mod, calls = _fake(tmp_path / "slot-owner.json", ctor_error="must not construct")
    res = local_lease.release_agent(AGENT, module=mod, which=_which)
    assert res == {"outcome": "disabled", "endpoints": []}
    assert calls == []


def test_cli_release_with_agent_id_prints_the_outcome(tmp_path, monkeypatch, capsys):
    mod, calls = _fake(_state(tmp_path, EP), holders={EP: AGENT})
    monkeypatch.setattr(local_lease, "slot_owner_module", lambda which=shutil.which: mod)
    assert local_lease.main(["release", "--agent-id", AGENT]) == 0
    assert capsys.readouterr().out.strip() == "lease: released (released)"
    assert calls == [(EP, AGENT)]


def test_cli_bare_release_prints_plain_and_never_touches_the_router(monkeypatch, capsys):
    def _loader(which=shutil.which):
        raise AssertionError("a bare release must not load the router module")

    monkeypatch.setattr(local_lease, "slot_owner_module", _loader)
    assert local_lease.main(["release"]) == 0
    assert capsys.readouterr().out.strip() == "lease: released"


def test_cli_release_agent_id_with_the_switch_never_reaches_the_live_router():
    """End to end: the flag parses, the switch answers, the operator's slot survives."""
    env = {**os.environ, "TP_SLOT_RELEASE": "0"}
    res = subprocess.run([sys.executable, str(SCRIPT), "release", "--agent-id", AGENT],
                         capture_output=True, text=True, env=env, timeout=30)
    assert (res.returncode, res.stdout.strip()) == (0, "lease: released (disabled)")
