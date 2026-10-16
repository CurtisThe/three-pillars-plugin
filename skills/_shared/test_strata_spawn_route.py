"""test_strata_spawn_route.py — the route-check seam that makes `unhealthy` reachable.

design: local-role-routing (Task 2.7, impl-audit retry 2). The impl-audit found
that `wait` exit 4 and `decide -> halt` were unreachable: nothing ever produced
`unhealthy` (council/impl-audit r1-codebase-fit, minor). `wait` now probes the
session's route through an injectable `route_check` and halts when the route is
not `routed`; a check that fails open (raises / malformed) keeps the lease path
and says so in `why`.

Hermetic (test-fragility.md): every case injects a callable or a fake lease, so
no test touches a live router, and the assertions are on structured route
results — never on prose.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parent
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

import local_lease  # noqa: E402
import local_route_check  # noqa: E402
import strata_spawn  # noqa: E402

BAD_ROUTES = [("router-down", "connect-refused")]
UNROUTED = [("unrouted", "no-base-url")]


class FakeLease:
    POLL_S = local_lease.POLL_S

    def __init__(self, state="free", why="unowned", waited=0.0):
        self.ret = (state, why, waited)
        self.calls = []

    def acquire_timed(self, **kw):
        self.calls.append(kw)
        return self.ret


class FakeRoute:
    """An injected `route_check`: counts calls, returns a result-v1 dict."""

    def __init__(self, state, reason=None):
        self.state = state
        self.reason = reason if reason is not None else state
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return {"schema": local_route_check.SCHEMA, "state": self.state,
                "reason": self.reason, "base_url": None, "checked_at": "x",
                "ollama": None, "detail": ""}


def run(policy, route_check, *, lease=None, **kw):
    lease = lease or FakeLease()
    out = strata_spawn.wait(design="d", policy=policy, lease=lease,
                            route_check=route_check, **kw)
    return out, lease


# --- the halt: a non-`routed` route is `unhealthy`, and the lease is untouched ---

@pytest.mark.parametrize("policy", ["fallback", "wait"])
@pytest.mark.parametrize("state,reason", BAD_ROUTES)
def test_bad_route_halts_without_touching_the_lease(policy, state, reason):
    check = FakeRoute(state, reason)
    (got, why, waited), lease = run(policy, check)
    assert (got, waited) == ("unhealthy", 0.0)
    assert reason in why and "route" in why.lower()
    assert "sonnet" not in (got + why).lower()
    assert check.calls == 1 and lease.calls == []


@pytest.mark.parametrize("state,reason", BAD_ROUTES)
def test_bad_route_halts_even_past_the_ceiling(state, reason):
    # the route fault is the actionable halt, so it is read before the ceiling.
    (got, _why, _w), lease = run("wait", FakeRoute(state, reason),
                                 started_at=0.0, ceiling_s=100, clock=lambda: 1000.0)
    assert got == "unhealthy" and lease.calls == []


@pytest.mark.parametrize("state,reason", UNROUTED)
def test_unrouted_route_is_its_own_state(state, reason):
    (got, why, waited), lease = run("wait", FakeRoute(state, reason),
                                    started_at=0.0, ceiling_s=100, clock=lambda: 1000.0)
    assert (got, waited) == ("unrouted", 0.0) and reason in why and lease.calls == []


def test_routed_route_leaves_the_wait_path_unchanged():
    for policy, expect in (("fallback", "busy-fallback"), ("wait", "still-busy")):
        check = FakeRoute("routed", "ok")
        lease = FakeLease("busy", "slot held by abcd1234")
        (got, why, _w), lease = run(policy, check, lease=lease)
        assert got == expect
        assert why == "slot held by abcd1234"  # no note on a healthy route
        assert check.calls == 1 and len(lease.calls) == 1


def test_routed_route_still_exhausts_at_the_ceiling():
    (got, _why, _w), lease = run("wait", FakeRoute("routed", "ok"),
                                 started_at=0.0, ceiling_s=100, clock=lambda: 1000.0)
    assert got == "wait-exhausted" and lease.calls == []


# --- fail-open: a route check that cannot answer never blocks a spawn ---

@pytest.mark.parametrize("policy", ["fallback", "wait"])
def test_raising_route_check_is_fail_open(policy):
    def boom():
        raise RuntimeError("probe exploded")
    (got, why, _w), lease = run(policy, boom)
    assert got == "free" and len(lease.calls) == 1
    assert "route check" in why.lower()


@pytest.mark.parametrize("bad", [None, {}, {"state": None}, "routed", 7])
def test_malformed_route_result_is_fail_open(bad):
    (got, why, _w), lease = run("fallback", lambda: bad)
    assert got == "free" and len(lease.calls) == 1
    assert "route check" in why.lower()


# --- the default probe: read-only, and never live behind a test seam ---

def test_default_probe_is_the_read_only_route_check(monkeypatch):
    seen = []

    def fake_check(*args, **kw):
        seen.append((args, kw))
        return FakeRoute("router-down", "connect-refused")()

    monkeypatch.setattr(local_route_check, "check", fake_check)
    got = strata_spawn._default_route_check()
    assert got["state"] == "router-down" and got["reason"] == "connect-refused"
    assert seen == [((), {})]


def test_real_lease_is_captured_at_import():
    assert strata_spawn._REAL_LEASE is local_lease


@pytest.mark.parametrize("lease,expect", [
    ("real", "_default_route_check"), ("fake", None)])
def test_the_default_probe_runs_only_for_the_real_lease(lease, expect, monkeypatch):
    # an injected (fake) lease is the test seam: no default probe, so the
    # existing wait/CLI tests stay hermetic with or without ANTHROPIC_BASE_URL.
    chosen = strata_spawn._route_probe(
        None, strata_spawn._REAL_LEASE if lease == "real" else FakeLease())
    assert (chosen.__name__ if chosen is not None else None) == expect


def test_injected_check_wins_over_the_default(monkeypatch):
    monkeypatch.setattr(local_route_check, "check",
                        lambda *a, **k: pytest.fail("the default probe ran"))
    check = FakeRoute("unrouted", "non-loopback")
    (got, _why, _w), lease = run("wait", check, lease=FakeLease())
    assert got == "unrouted" and lease.calls == []


# --- the CLI: exit 4 on the unhealthy path, 0 on a routed one ---

def _cli_wait(monkeypatch, capsys, tmp_path, lease, check):
    cfg = tmp_path / "empty.json"
    cfg.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(strata_spawn, "local_lease", lease)
    monkeypatch.setattr(strata_spawn, "_ROUTE_CHECK", check)
    code = strata_spawn.main(["wait", "--config", str(cfg)])
    return code, json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("state,reason", BAD_ROUTES)
def test_cli_wait_unhealthy_exits_4(monkeypatch, capsys, tmp_path, state, reason):
    lease = FakeLease()
    code, data = _cli_wait(monkeypatch, capsys, tmp_path, lease, FakeRoute(state, reason))
    assert code == 4
    assert data["state"] == "unhealthy" and reason in data["why"]
    assert lease.calls == []


def test_cli_wait_routed_falls_through_to_the_lease(monkeypatch, capsys, tmp_path):
    lease = FakeLease()
    check = FakeRoute("routed", "ok")
    code, data = _cli_wait(monkeypatch, capsys, tmp_path, lease, check)
    assert code == 0
    assert data["state"] == "free" and check.calls == 1 and len(lease.calls) == 1
