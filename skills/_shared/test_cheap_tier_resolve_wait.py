"""Tests for the busy-policy branch of `cheap_tier.resolve` and `spec --busy-policy wait`.

design: one-cheap-engine (Task 2.4; skills/_shared/test-fragility.md).

Under `fallback` (the default) `resolve` is unchanged. Under `wait` a busy lease keeps the
local rung and answers `wait` (`cheap_engine.busy_action`), then `halt` once the wait reaches
`strata_spawn.CEILING_S`; a route that is not `routed/ok` still mirrors to Sonnet (M51). The
CLI makes one bounded `strata_spawn.wait` call per `spec`; here that call and
`cheap_route.probe` are stubbed, so no test reaches a lease, a router or a model.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cheap_route  # noqa: E402
import cheap_tier  # noqa: E402
import cheap_tier_cli as cli  # noqa: E402
import strata_spawn  # noqa: E402
import wait_budget  # noqa: E402

CEILING = strata_spawn.CEILING_S
ROUTED = json.dumps({"schema": "tp-local-route/v1", "state": "routed", "reason": "ok",
                     "base_url": "http://127.0.0.1:3457", "checked_at": "2026-10-08T00:00:00Z"})
LOCAL = {"enabled": True, "model": "qwen3-coder", "fallback_model": "sonnet"}


def _resolve(lease_state="busy", label="routed/ok", **kw):
    return cheap_tier.resolve("local-xhigh", route_label=label, lease_state=lease_state, **kw)


def test_resolve_wait_keeps_local_rung():
    for lease in ("busy", "busy-measure"):
        assert _resolve(lease, busy_policy="wait", waited_since=1000.0, now=1100.0) == (
            "local-xhigh", "wait")
    assert _resolve(busy_policy="wait", now=5000.0) == ("local-xhigh", "wait")  # first poll
    assert _resolve("free", busy_policy="wait") == (
        "local-xhigh", "local-xhigh: routed/ok, lease free")
    assert _resolve(busy_policy="wait", waited_since=0.0, now=CEILING - 1) == (
        "local-xhigh", "wait")


def test_resolve_wait_halts_at_ceiling():
    assert _resolve(busy_policy="wait", waited_since=0.0, now=CEILING) == ("local-xhigh", "halt")
    assert _resolve("busy-measure", busy_policy="wait", waited_since=10.0,
                    now=10.0 + CEILING + 5) == ("local-xhigh", "halt")


def test_resolve_wait_still_mirrors_an_unrouted_route():
    """M51: waiting is for a busy slot, never for a missing router."""
    for label in ("unrouted/no-base-url", "router-down/connect-refused", "missing-route"):
        rung, why = _resolve("unchecked", label=label, busy_policy="wait", waited_since=0.0,
                             now=1.0)
        assert rung == "sonnet-xhigh" and label in why


def test_resolve_fallback_unchanged():
    assert _resolve() == ("sonnet-xhigh", "local-xhigh->sonnet-xhigh: lease busy")
    assert _resolve(busy_policy="fallback", waited_since=0.0, now=CEILING * 2) == (
        "sonnet-xhigh", "local-xhigh->sonnet-xhigh: lease busy")
    assert _resolve("free") == ("local-xhigh", "local-xhigh: routed/ok, lease free")
    assert _resolve("unchecked", label="missing-route") == (
        "sonnet-xhigh", "local-xhigh->sonnet-xhigh: route missing-route")
    assert cheap_tier.resolve("sonnet-medium", route_label="x", lease_state="busy",
                              busy_policy="wait") == ("sonnet-medium",
                                                      "sonnet-medium: not a local rung")


# --- the CLI: one bounded strata_spawn.wait per spec --------------------------------------


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.delenv("TP_LOCAL", raising=False)
    monkeypatch.delenv("TP_LOCAL_MODE", raising=False)


@pytest.fixture
def busy(monkeypatch):
    """Fake the lease busy through `cheap_route.probe` and stub `strata_spawn.wait`."""
    waits = []
    reply = {"value": ("still-busy", "slot held by agent abcd1234",
                       float(wait_budget.WAIT_BUDGET_S))}

    def fake_probe(slot, rung, root, **kwargs):
        return {"route_label": "routed/ok", "lease_state": "busy", "lease_why": "held",
                "lease_wait_s": 0.0, "measure": "off", "fallback": "local-busy"}

    def fake_wait(design=None, budget_s=wait_budget.WAIT_BUDGET_S, started_at=None,
                  ceiling_s=CEILING,
                  policy="fallback", **kwargs):
        waits.append({"design": design, "budget_s": budget_s, "started_at": started_at,
                      "ceiling_s": ceiling_s, "policy": policy})
        return reply["value"]

    monkeypatch.setattr(cheap_route, "probe", fake_probe)
    monkeypatch.setattr(strata_spawn, "wait", fake_wait)
    return waits, reply


def _root(tmp_path: Path) -> Path:
    cfg = tmp_path / ".three-pillars" / "config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"models": {"docs_draft": "local-medium"},
                               "local_implement": LOCAL}), encoding="utf-8")
    return tmp_path


def _spec(capsys, root: Path, *extra: str):
    code = cli.main(["spec", "--slot", "docs_draft", "--root", str(root), "--probe",
                     "--design", "D", "--route", ROUTED, *extra])
    out, err = capsys.readouterr()
    return code, json.loads(out), err


def test_spec_cli_wait_prints_wait_then_halt(tmp_path, capsys, busy):
    waits, _reply = busy
    root = _root(tmp_path)
    before = time.time()
    code, first, _err = _spec(capsys, root, "--busy-policy", "wait")
    assert code == 0 and first["action"] == "wait" and first["rung"] == "local-medium"
    assert before <= first["waited_since"] <= time.time()
    assert first["fallback"] is None and first["agent"] == "tp-drafter"
    assert [(w["design"], w["budget_s"], w["policy"]) for w in waits] == [
        ("D", wait_budget.WAIT_BUDGET_S, "wait")]
    assert waits[0]["started_at"] == first["waited_since"]
    since = time.time() - 100
    _code, again, _err = _spec(capsys, root, "--busy-policy", "wait", "--waited-since",
                               str(since))
    assert again["action"] == "wait" and again["waited_since"] == since
    assert waits[-1]["started_at"] == since
    waits.clear()
    past = time.time() - CEILING - 60
    code, halted, _err = _spec(capsys, root, "--busy-policy", "wait", "--waited-since",
                               str(past))
    assert code == 0 and halted["action"] == "halt" and halted["rung"] == "local-medium"
    assert halted["waited_since"] == past


def test_spec_cli_wait_exhausted_halts(tmp_path, capsys, busy):
    _waits, reply = busy
    reply["value"] = ("wait-exhausted", "waited past the ceiling", 0.0)
    _code, spec, _err = _spec(capsys, _root(tmp_path), "--busy-policy", "wait")
    assert spec["action"] == "halt"


def test_spec_cli_wait_that_finds_the_slot_free_keeps_the_rung(tmp_path, capsys, busy):
    _waits, reply = busy
    reply["value"] = ("free", "unowned", 12.0)
    _code, spec, _err = _spec(capsys, _root(tmp_path), "--busy-policy", "wait")
    assert "action" not in spec and spec["rung"] == "local-medium"
    assert spec["why"] == "local-medium: routed/ok, lease free"


def test_spec_cli_fallback_never_waits(tmp_path, capsys, busy):
    waits, _reply = busy
    _code, spec, _err = _spec(capsys, _root(tmp_path), "--busy-policy", "fallback")
    assert waits == [] and "action" not in spec
    assert spec["rung"] == "sonnet-medium" and spec["fallback"] == "local-busy"
    assert _spec(capsys, _root(tmp_path))[1] == spec  # the default is fallback


def test_busy_policy_default_comes_from_tp_local_mode(tmp_path, capsys, busy, monkeypatch):
    waits, _reply = busy
    monkeypatch.setenv("TP_LOCAL_MODE", "wait")
    _code, spec, _err = _spec(capsys, _root(tmp_path))
    assert spec["action"] == "wait" and len(waits) == 1
