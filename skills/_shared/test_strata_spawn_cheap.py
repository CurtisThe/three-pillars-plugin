"""Tests for strata_spawn under the one-cheap-engine rule (Task 2.3).

busy comes from TP_LOCAL_MODE, `unrouted` is its own state (exit 6), and
`decide` names Sonnet where it used to name Opus. Hermetic: injected lease and
route check, TP_LOCAL_MODE set/cleared explicitly (test-fragility.md).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parent
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

import strata_spawn  # noqa: E402

ROLES = ("council_member", "review_finder", "context_scout")
CFG_FALLBACK = {"strata_spawn": {"busy": "fallback"}}
CFG_WAIT = {"strata_spawn": {"busy": "wait"}}


class FakeLease:
    POLL_S = 1

    def __init__(self):
        self.calls = []

    def acquire_timed(self, **kw):
        self.calls.append(kw)
        return "free", "unowned", 0.0


def _route(state, reason="r"):
    return lambda: {"state": state, "reason": reason}


def test_tp_local_mode_wait_beats_config():
    assert strata_spawn.busy_policy(CFG_FALLBACK, None, {"TP_LOCAL_MODE": "wait"}) == "wait"


def test_exclusive_is_wait():
    assert strata_spawn.busy_policy({}, None, {"TP_LOCAL_MODE": "exclusive"}) == "wait"


def test_override_beats_tp_local_mode():
    assert strata_spawn.busy_policy({}, "fallback", {"TP_LOCAL_MODE": "wait"}) == "fallback"


def test_unset_falls_through_to_config():
    assert strata_spawn.busy_policy(CFG_WAIT, None, {}) == "wait"
    assert strata_spawn.busy_policy({}, None, {}) == "fallback"


def test_unrouted_is_its_own_state(monkeypatch, capsys, tmp_path):
    lease = FakeLease()
    got, why, waited = strata_spawn.wait(design="d", lease=lease,
                                         route_check=_route("unrouted", "no-base-url"))
    assert (got, waited) == ("unrouted", 0.0) and lease.calls == []
    assert "no-base-url" in why
    monkeypatch.delenv("TP_LOCAL_MODE", raising=False)
    cfg = tmp_path / "c.json"
    cfg.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(strata_spawn, "local_lease", lease)
    monkeypatch.setattr(strata_spawn, "_ROUTE_CHECK", _route("unrouted"))
    assert strata_spawn.main(["wait", "--config", str(cfg)]) == 6
    assert json.loads(capsys.readouterr().out)["state"] == "unrouted"


def test_router_down_still_halts():
    lease = FakeLease()
    got, _why, _w = strata_spawn.wait(design="d", lease=lease,
                                      route_check=_route("router-down", "refused"))
    assert got == "unhealthy" and lease.calls == []
    assert strata_spawn.decide(0, "unhealthy", "council_member") == "halt"


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("attempt", [0, 2])
def test_unrouted_decides_sonnet(role, attempt):
    assert strata_spawn.decide(attempt, "unrouted", role) == "sonnet"


@pytest.mark.parametrize("policy", ["fallback", "wait"])
@pytest.mark.parametrize("attempt", [2, 3])
def test_exhausted_decides_sonnet_never_opus(policy, attempt):
    for role in ("council_member", "review_finder"):
        assert strata_spawn.decide(attempt, "fallback", role, policy) == "sonnet"
    assert strata_spawn.decide(attempt, "fallback", "context_scout", policy) == "proceed-empty"
    for served in strata_spawn.SERVED_STATES:
        for role in ROLES:
            assert strata_spawn.decide(attempt, served, role, policy) != "opus"
