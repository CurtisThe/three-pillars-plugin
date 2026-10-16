"""Tests for strata_spawn.decide / release (local-role-routing Task 2.3)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parent
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

import local_lease  # noqa: E402
import strata_spawn  # noqa: E402

ROLES = ("council_member", "review_finder", "context_scout")
POLICIES = ("fallback", "wait")
SERVED = ("strata", "fallback-busy", "fallback", "unhealthy", "unrouted")
ALL_OUT = {"accept", "respawn", "sonnet", "proceed-empty", "halt"}


def test_respawn_max_is_two():
    assert strata_spawn.RESPAWN_MAX == 2


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("attempt", [0, 1, 2, 3])
@pytest.mark.parametrize("policy", POLICIES)
def test_strata_accepts(role, attempt, policy):
    msg = f"role={role} attempt={attempt} policy={policy}"
    assert strata_spawn.decide(attempt, "strata", role, policy) == "accept", msg


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("attempt", [0, 1, 2, 3])
def test_fallback_busy_default_policy_accepts(role, attempt):
    msg = f"role={role} attempt={attempt} policy=default"
    assert strata_spawn.decide(attempt, "fallback-busy", role) == "accept", msg
    msg = f"role={role} attempt={attempt} policy=fallback"
    assert strata_spawn.decide(attempt, "fallback-busy", role, "fallback") == "accept", msg


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("attempt", [0, 1, 2, 3])
def test_fallback_busy_under_wait_equals_fallback(role, attempt):
    msg = f"role={role} attempt={attempt} policy=wait"
    assert (strata_spawn.decide(attempt, "fallback-busy", role, "wait")
            == strata_spawn.decide(attempt, "fallback", role, "wait")), msg


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize("attempt", [0, 1])
def test_fallback_respawns_below_max(role, policy, attempt):
    msg = f"role={role} attempt={attempt} policy={policy}"
    assert strata_spawn.decide(attempt, "fallback", role, policy) == "respawn", msg


@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize("attempt", [2, 3])
def test_fallback_exhausted(policy, attempt):
    msg = f"role=council_member attempt={attempt} policy={policy}"
    assert strata_spawn.decide(attempt, "fallback", "council_member", policy) == "sonnet", msg
    msg = f"role=review_finder attempt={attempt} policy={policy}"
    assert strata_spawn.decide(attempt, "fallback", "review_finder", policy) == "sonnet", msg
    msg = f"role=context_scout attempt={attempt} policy={policy}"
    assert (strata_spawn.decide(attempt, "fallback", "context_scout", policy)
            == "proceed-empty"), msg


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("attempt", [0, 1, 2, 3])
@pytest.mark.parametrize("policy", POLICIES)
def test_unhealthy_halts(role, attempt, policy):
    msg = f"role={role} attempt={attempt} policy={policy}"
    assert strata_spawn.decide(attempt, "unhealthy", role, policy) == "halt", msg


def test_no_output_names_opus():
    for s in SERVED:
        for r in ROLES:
            for p in POLICIES:
                for a in range(4):
                    out = strata_spawn.decide(a, s, r, p)
                    msg = f"role={r} attempt={a} policy={p}"
                    assert out in ALL_OUT, msg
                    assert "opus" not in out.lower(), msg


def test_unknown_inputs_raise():
    with pytest.raises(ValueError):
        strata_spawn.decide(0, "strata", "judge")
    with pytest.raises(ValueError):
        strata_spawn.decide(0, "strata", "council_member", "sometimes")
    with pytest.raises(ValueError):
        strata_spawn.decide(0, "bogus", "council_member")


def test_release_calls_injected():
    calls = []
    strata_spawn.release("a1", release_agent=lambda a: calls.append(a))
    assert calls == ["a1"]


def test_release_defaults_to_local_lease(monkeypatch):
    calls = []
    monkeypatch.setattr(local_lease, "release_agent", lambda a, **kw: calls.append(a))
    strata_spawn.release("a1")
    assert calls == ["a1"]
