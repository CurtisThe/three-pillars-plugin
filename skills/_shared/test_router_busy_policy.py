"""Tests for router_busy_policy + its lease wiring (design: wait-mode-router-leak).

The lease records the run's busy policy beside the router's slot state, keyed by the
session id the router sees on every request; a probe that loses the router's lock budget
reads ``peek`` instead of answering ``unchecked`` (the gap that spawned into a held slot).
Fakes only: no test reaches the live router or its state dir. test-fragility.md: assertions
are on the file's parsed JSON and the lease's returned state, never on log wording.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cheap_engine  # noqa: E402
import local_lease  # noqa: E402
import router_busy_policy as rbp  # noqa: E402

ME, OTHER = "1b41f03f-me", "82e3b4ad-other"


def _read(state):
    return json.loads(Path(rbp.path_for(str(state))).read_text(encoding="utf-8"))


@pytest.mark.parametrize("value", ["", "fallback", "wait", "exclusive", "bogus"])
def test_policy_from_env_agrees_with_cheap_engine(value):
    assert rbp.policy_from_env({"TP_LOCAL_MODE": value}) == cheap_engine.local_mode(
        {"TP_LOCAL_MODE": value})[0]


def test_record_writes_beside_the_slot_state_and_prunes_stale(tmp_path):
    state = tmp_path / "tp-local" / "slot-owner.json"
    assert rbp.record(str(state), OTHER, "wait", clock=lambda: 1000.0)
    assert rbp.record(str(state), ME, "wait", clock=lambda: 1000.0 + rbp.TTL_S + 1)
    assert _read(state) == {ME: {"policy": "wait", "at": 1000.0 + rbp.TTL_S + 1}}
    assert rbp.record(str(state), ME, "fallback", clock=lambda: 5.0e4)
    assert _read(state)[ME]["policy"] == "fallback"


@pytest.mark.parametrize("session,policy", [(None, "wait"), ("", "wait"), (ME, "bogus")])
def test_record_refuses_without_a_session_or_a_known_policy(tmp_path, session, policy):
    state = tmp_path / "slot-owner.json"
    assert not rbp.record(str(state), session, policy)
    assert not Path(rbp.path_for(str(state))).exists()


def test_record_survives_a_corrupt_file(tmp_path):
    state = tmp_path / "slot-owner.json"
    Path(rbp.path_for(str(state))).write_text("{not json", encoding="utf-8")
    assert rbp.record(str(state), ME, "wait", clock=lambda: 7.0)
    assert _read(state) == {ME: {"policy": "wait", "at": 7.0}}


class _Owner:
    """A router SlotOwner stand-in: ``acquire`` answers ``why``; ``peek`` answers ``peeked``."""

    def __init__(self, state_path, why="unowned", peeked=(True, None)):
        self.state_path, self.why, self.peeked = str(state_path), why, peeked

    def acquire(self, endpoint, key, subagent):
        return None, self.why

    def peek(self, endpoint):
        return self.peeked


def _module(owner):
    return type("M", (), {"SlotOwner": lambda self=None: owner})


def _state(tmp_path):
    state = tmp_path / "slot-owner.json"
    state.write_text(json.dumps({"E": {}}), encoding="utf-8")
    return state


@pytest.mark.parametrize("env_mode,flag,want", [("wait", None, "wait"), ("", None, "fallback"),
                                                ("", "wait", "wait"), ("exclusive", None, "wait")])
def test_acquire_records_the_effective_policy(tmp_path, env_mode, flag, want):
    state = _state(tmp_path)
    env = {"CLAUDE_CODE_SESSION_ID": ME, "TP_LOCAL_MODE": env_mode}
    local_lease.acquire_timed(env=env, module=_module(_Owner(state)), busy_policy=flag)
    assert _read(state)[ME]["policy"] == want


def test_acquire_records_even_when_busy(tmp_path):
    state = _state(tmp_path)
    env = {"CLAUDE_CODE_SESSION_ID": ME, "TP_LOCAL_MODE": "wait"}
    got = local_lease.acquire(env=env, module=_module(_Owner(state, f"slot held by {OTHER[:8]}")))
    assert got[0] == "busy" and _read(state)[ME]["policy"] == "wait"


def test_lock_contention_reads_peek_instead_of_unchecked(tmp_path):
    """The 2026-10-09 19:24 leak: the probe lost the 50 ms lock budget to a router serving
    another run back to back; ``unchecked`` spawned into a slot that run held."""
    owner = _Owner(_state(tmp_path), "slot state busy", peeked=(False, OTHER[:8]))
    env = {"CLAUDE_CODE_SESSION_ID": ME}
    assert local_lease.acquire(env=env, module=_module(owner)) == (
        "busy", f"slot held by {OTHER[:8]}")
    owner.peeked = (True, None)
    assert local_lease.acquire(env=env, module=_module(owner)) == ("free", "unowned")


def test_lock_contention_without_peek_stays_unchecked(tmp_path):
    class Old(_Owner):
        peek = None
    owner = Old(_state(tmp_path), "slot state busy")
    state, _why = local_lease.acquire(env={"CLAUDE_CODE_SESSION_ID": ME}, module=_module(owner))
    assert state == "unchecked"


def test_cli_busy_policy_flag(tmp_path, monkeypatch, capsys):
    state = _state(tmp_path)
    monkeypatch.setattr(local_lease, "slot_owner_module", lambda which=None: _module(_Owner(state)))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", ME)
    monkeypatch.delenv("TP_LOCAL_MODE", raising=False)
    assert local_lease.main(["acquire", "--busy-policy", "wait"]) == 0
    assert _read(state)[ME]["policy"] == "wait"


@pytest.mark.parametrize("policy", ["wait", "fallback"])
def test_strata_spawn_wait_hands_its_policy_to_the_lease(policy):
    """``strata_spawn.busy: wait`` in config (no TP_LOCAL_MODE) still reaches the router."""
    import strata_spawn

    class Lease:
        kw = None

        def acquire_timed(self, **kw):
            Lease.kw = kw
            return "free", "unowned", 0.0

    strata_spawn.wait("d", 10, None, policy=policy, lease=Lease())
    assert Lease.kw["busy_policy"] == policy


def test_acquire_reads_the_repo_config_policy_when_env_is_unset(tmp_path, monkeypatch, capsys):
    """Review fix: spec / cheap_route / ladder leases pass no policy; config ``wait`` must stick."""
    state = _state(tmp_path)
    (tmp_path / ".three-pillars").mkdir()
    (tmp_path / ".three-pillars" / "config.json").write_text(
        json.dumps({"strata_spawn": {"busy": "wait"}}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    local_lease.acquire(env={"CLAUDE_CODE_SESSION_ID": ME}, module=_module(_Owner(state)))
    assert _read(state)[ME]["policy"] == "wait"


def test_a_wait_policy_that_cannot_be_recorded_warns(tmp_path, capsys):
    local_lease.acquire(env={"TP_LOCAL_MODE": "wait"}, module=_module(_Owner(_state(tmp_path))))
    assert "not recorded" in capsys.readouterr().err
