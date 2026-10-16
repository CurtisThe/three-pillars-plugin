"""Tests for strata_spawn.busy_policy / wait (local-role-routing Task 2.1).

A fake lease, clock and sleep are injected; no live router is touched.
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
import strata_spawn  # noqa: E402
import wait_budget  # noqa: E402


class FakeLease:
    POLL_S = local_lease.POLL_S

    def __init__(self, state="free", why="ok", waited=0.0):
        self.ret = (state, why, waited)
        self.calls = []

    def acquire_timed(self, **kw):
        self.calls.append(kw)
        return self.ret


def run(state, policy, *, waited=0.0, started_at=None, now=1000.0, **kw):
    lease = FakeLease(state, "why", waited)
    sleeps = []
    out = strata_spawn.wait(
        design="d", policy=policy, started_at=started_at, lease=lease,
        clock=lambda: now, sleep=sleeps.append, **kw)
    return out, lease, sleeps


def test_policy_constants():
    assert strata_spawn.BUSY_POLICIES == ("fallback", "wait")
    assert strata_spawn.DEFAULT_BUSY == "fallback"
    assert strata_spawn.CEILING_S == 4 * 3600
    assert strata_spawn.POLL_S == 15


def test_busy_policy_resolution(capsys, monkeypatch):
    monkeypatch.delenv("TP_LOCAL_MODE", raising=False)
    assert strata_spawn.busy_policy({}) == "fallback"
    assert strata_spawn.busy_policy({"strata_spawn": {"busy": "wait"}}) == "wait"
    assert strata_spawn.busy_policy({"strata_spawn": {"busy": "wait"}}, "fallback") == "fallback"
    assert capsys.readouterr().err == ""
    assert strata_spawn.busy_policy({"strata_spawn": {"busy": "bogus"}}) == "fallback"
    assert len(capsys.readouterr().err.strip().splitlines()) == 1
    assert strata_spawn.busy_policy({}, env={"TP_LOCAL_MODE": "wait"}) == "wait"


def test_schema_and_docs_name_the_block():
    schema = json.loads((_DIR / "repo-config.schema.json").read_text(encoding="utf-8"))
    block = schema["properties"]["strata_spawn"]
    assert block["type"] == "object"
    assert block["additionalProperties"] is False
    assert tuple(block["properties"]["busy"]["enum"]) == strata_spawn.BUSY_POLICIES
    assert "strata_spawn.busy" in (_DIR / "repo-config.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("state,expect", [
    ("free", "free"), ("busy", "busy-fallback"),
    ("unhealthy", "unhealthy"), ("unchecked", "unchecked")])
def test_fallback_policy_maps_without_sleep(state, expect):
    (got, _why, _w), lease, sleeps = run(state, "fallback")
    assert got == expect
    assert sleeps == []
    assert len(lease.calls) == 1 and lease.calls[0]["wait_s"] == strata_spawn.BUSY_GRACE_S


def test_fallback_busy_measure_sleeps_once():
    (got, _, _), lease, sleeps = run("busy-measure", "fallback")
    assert got == "still-busy"
    assert sleeps == [15]
    assert len(lease.calls) == 1


def test_fallback_ignores_ceiling():
    (got, _, _), lease, _ = run("free", "fallback", started_at=0.0, now=10 * 3600)
    assert got == "free" and len(lease.calls) == 1


@pytest.mark.parametrize("state,expect", [
    ("free", "free"), ("busy", "still-busy"),
    ("unhealthy", "unhealthy"), ("unchecked", "unchecked")])
def test_wait_policy_maps_states(state, expect):
    (got, _why, _w), lease, sleeps = run(state, "wait", budget_s=300)
    assert got == expect
    assert sleeps == []
    assert len(lease.calls) == 1 and lease.calls[0]["wait_s"] == 300


def test_wait_busy_measure_sleeps_once():
    (got, _, _), lease, sleeps = run("busy-measure", "wait", waited=0.0)
    assert got == "still-busy"
    assert sleeps == [15]


def test_wait_default_budget_is_the_wait_budget():
    _, lease, _ = run("free", "wait")
    assert lease.calls[0]["wait_s"] == wait_budget.WAIT_BUDGET_S


def test_wait_ceiling_exhausts_without_lease_call():
    (got, _, _), lease, _ = run("free", "wait", started_at=0.0, now=4 * 3600)
    assert got == "wait-exhausted"
    assert lease.calls == []


def test_wait_ceiling_override_and_under_ceiling():
    (got, _, _), lease, _ = run("free", "wait", started_at=900.0, now=1000.0, ceiling_s=100)
    assert got == "wait-exhausted" and lease.calls == []
    (got, _, _), lease, _ = run("free", "wait", started_at=901.0, now=1000.0, ceiling_s=100)
    assert got == "free" and len(lease.calls) == 1


@pytest.mark.parametrize("policy", ["fallback", "wait"])
@pytest.mark.parametrize("state", ["free", "busy", "busy-measure", "unhealthy", "unchecked"])
def test_no_state_names_sonnet(policy, state):
    (got, _, _), _, _ = run(state, policy)
    assert "sonnet" not in got.lower()
