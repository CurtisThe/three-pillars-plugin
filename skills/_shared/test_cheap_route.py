"""test_cheap_route.py — `cheap_route.probe`: route, window, orphans and lease for a cheap slot.

design: cheap-tier-local-routing (detailed-design.md §Interfaces `cheap_route.probe`, §Notes 4)

Every seam is injected. `check` (the live `/health` route check) and `lease`
(`local_lease.acquire_timed`) are recording fakes; `orphans` is the real
`attempt_orphans.orphans` pinned to a tmp router log and an empty config dir, so its phase
filter and its running/done rule are the shipped ones. The measurement window lives under
`XDG_STATE_HOME = tmp_path` (built by `measure_window`'s own CLI) and the task ladder under a
tmp git repo's common dir. No network, no operator state.
"""
from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path

import pytest

import attempt_orphans
import attempt_watchdog
import cheap_route
import cheap_tier
import local_route_check
import local_route_log
import measure_window
import served_rung
from task_scope import _git_env as clean_git_env

LOOPBACK = "http://127.0.0.1:3457"
SLOT, RUNG = "docs_draft", "local-medium"
KEYS = {"route_label", "lease_state", "lease_why", "lease_wait_s", "measure", "fallback"}


def _result(state, reason, base_url=None) -> dict:
    return {"schema": local_route_check.SCHEMA, "state": state, "reason": reason,
            "base_url": base_url, "checked_at": "2026-10-02T00:00:00Z", "ollama": None,
            "detail": ""}


OK = _result("routed", "ok", local_route_check.redact_url(LOOPBACK))
DOWN = _result("router-down", "timeout", local_route_check.redact_url(LOOPBACK))


def _text(result) -> str:
    """Decisions.md text whose open `[routing]` window holds `result`."""
    return "# Decisions log — schema v1\n\n" + local_route_log.render_entry(
        result, "run-start", "none") + "\n"


class Seams:
    """Recording fakes for `check` and `lease`; the real orphan predicate on tmp state."""

    def __init__(self, tmp_path, *, route=OK, lease=("free", "unowned", 0.0)):
        self.route, self.answer = route, lease
        self.checks, self.leases, self.scans = [], [], []
        self.cfg, self.log = tmp_path / "claude-config", tmp_path / "router.log"
        self.cfg.mkdir(exist_ok=True)

    def check(self, env):
        self.checks.append(env)
        return self.route

    def lease(self, **kw):
        self.leases.append(kw)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer

    def orphans(self, ladder_dir, *, phase, **_kw):
        self.scans.append((Path(ladder_dir), phase))
        return attempt_orphans.orphans(ladder_dir, phase=phase, config_dir=self.cfg,
                                       router_log=self.log)


@pytest.fixture
def repo(tmp_path) -> Path:
    root = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(root)], check=True, env=clean_git_env())
    return root


@pytest.fixture
def env(tmp_path) -> dict:
    return {"HOME": str(tmp_path), "XDG_STATE_HOME": str(tmp_path / "state"),
            "ANTHROPIC_BASE_URL": LOOPBACK}


def _probe(seams, repo, env, *, slot=SLOT, rung=RUNG, design="demo", **kw) -> dict:
    out = cheap_route.probe(slot, rung, repo, design=design, env=env, check=seams.check,
                            lease=seams.lease, orphans=seams.orphans, **kw)
    return _shape(out, rung)


def _shape(out, rung=RUNG) -> dict:
    """Every branch: the six keys, a float wait, a known measure and fallback, and the
    rung `cheap_tier.resolve` gives stays local exactly when there is no fallback."""
    assert set(out) == KEYS
    assert isinstance(out["lease_wait_s"], float)
    assert out["measure"] in ("off", "owner", "other")
    assert out["fallback"] is None or out["fallback"] in served_rung.FALLBACKS
    if rung.startswith("local-"):
        kept = cheap_tier.resolve(rung, route_label=out["route_label"],
                                  lease_state=out["lease_state"])[0]
        assert (kept == rung) == (out["fallback"] is None)
    return out


def _window(env, design) -> None:
    started = dt.datetime.now(dt.timezone.utc)
    assert measure_window.main(["start", "--design", design, "--hours", "1"], env=env,
                               clock=lambda: started) == 0


def _orphan(dirpath: Path, name: str, *, phase: str, settled: bool = False) -> None:
    """An orphan-marked attempt; running until its stop settles (no transcript, no log)."""
    watch = dirpath / f"{name}.watch.json"
    attempt_watchdog.arm(watch, attempt_id=f"demo/{name}", agent_id=f"a{name}",
                         rung="local-medium", phase=phase, router_log=None, now=0.0)
    attempt_watchdog.mark_orphan(watch, now=1.0)
    if settled:
        attempt_orphans.mark_stopped(watch, result="ok", now=2.0)


def _ladder(repo: Path, slug: str) -> Path:
    return repo.resolve() / ".git" / "tp-ladder" / slug


def test_routed_slots_are_the_three_prose_drafters():
    assert cheap_route.ROUTED_SLOTS == {"history_line", "handoff", "docs_draft"}
    assert cheap_route.ROUTED_SLOTS <= set(cheap_tier.SLOTS)


@pytest.mark.parametrize("slot", sorted(set(cheap_tier.SLOTS) - {"history_line", "handoff",
                                                                  "docs_draft"}))
def test_slot_outside_routed_slots_is_unrouted_slot(tmp_path, repo, env, slot):
    seams = Seams(tmp_path)
    out = _probe(seams, repo, {**env, "ANTHROPIC_BASE_URL": ""}, slot=slot)
    assert (out["route_label"], out["fallback"]) == ("unrouted/slot", "unrouted-slot")
    assert out["lease_wait_s"] == 0.0
    assert (seams.checks, seams.leases, seams.scans) == ([], [], [])


def test_non_local_rung_is_never_probed(tmp_path, repo, env):
    seams = Seams(tmp_path)
    out = _probe(seams, repo, env, rung="sonnet-medium")
    assert (out["fallback"], out["lease_wait_s"]) == (None, 0.0)
    assert (seams.checks, seams.leases, seams.scans) == ([], [], [])


def test_consumer_without_base_url_is_unrouted_through_the_real_check(tmp_path, repo, env):
    seams = Seams(tmp_path)
    consumer = {k: v for k, v in env.items() if k != "ANTHROPIC_BASE_URL"}
    out = _shape(cheap_route.probe(SLOT, RUNG, repo, design="demo", env=consumer,
                                   lease=seams.lease, orphans=seams.orphans))
    assert out["route_label"] == "unrouted/no-base-url"
    assert (out["fallback"], out["lease_wait_s"]) == ("unrouted", 0.0)
    assert (seams.leases, seams.scans) == ([], [])


@pytest.mark.parametrize("given, label", [
    ({"route": DOWN}, "router-down/timeout"),
    ({"route": _result("router-down", "connect-refused")}, "router-down/connect-refused"),
    ({"route": _result("unrouted", "non-loopback")}, "unrouted/non-loopback"),
    ({"route": {"not": "a route"}}, "malformed-route"),
    ({"route_text": ""}, "missing-route"),
    ({"route_text": _text(_result("routed", "ok", "http://127.0.0.1:9"))}, "stale-route"),
])
def test_any_other_non_ok_label_is_unreachable(tmp_path, repo, env, given, label):
    seams = Seams(tmp_path)
    out = _probe(seams, repo, env, **given)
    assert (out["route_label"], out["fallback"]) == (label, "unreachable")
    assert out["lease_wait_s"] == 0.0
    assert (seams.leases, seams.scans) == ([], [])


@pytest.mark.parametrize("given, live, label, checked", [
    ({"route": DOWN, "route_text": _text(OK)}, OK, "router-down/timeout", False),
    ({"route_text": _text(OK)}, DOWN, "routed/ok", False),
    ({"route_text": _text(DOWN)}, OK, "router-down/timeout", False),
    ({}, DOWN, "router-down/timeout", True),
    ({}, OK, "routed/ok", True),
])
def test_route_precedence_route_then_text_then_live_check(tmp_path, repo, env, given, live,
                                                          label, checked):
    seams = Seams(tmp_path, route=live)
    out = _probe(seams, repo, env, **given)
    assert out["route_label"] == label
    assert seams.checks == ([env] if checked else [])


@pytest.mark.parametrize("answer, state, why, fallback", [
    (("free", "unowned", 0.0), "free", "unowned", None),
    (("free", "unowned", 30), "free", "unowned", None),
    (("busy", "slot held by 0b0e0b0e", 0.0), "busy", "slot held by 0b0e0b0e", "local-busy"),
    (("busy", "slot held by 0b0e0b0e", 540.0), "busy", "slot held by 0b0e0b0e", "local-busy"),
    (("busy-measure", "measurement window held by D", 0.0), "busy-measure",
     "measurement window held by D", "local-busy-measure"),
    (("unchecked", "no local router install", 0.0), "free", "unchecked", None),
])
def test_routed_ok_lease_states(tmp_path, repo, env, answer, state, why, fallback):
    seams = Seams(tmp_path, lease=answer)
    out = _probe(seams, repo, env)
    assert (out["route_label"], out["lease_state"], out["lease_why"], out["fallback"]) == (
        "routed/ok", state, why, fallback)
    assert out["lease_wait_s"] == float(answer[2])
    assert seams.leases == [{"design": "demo", "env": env}]


def test_task_orphan_any_phase_blocks_the_cheap_route(tmp_path, repo, env):
    _orphan(_ladder(repo, "demo"), "3.2", phase="3")
    seams = Seams(tmp_path)
    out = _probe(seams, repo, env)
    assert (out["fallback"], out["lease_wait_s"]) == ("orphan-holds-gpu", 0.0)
    assert seams.leases == []
    assert (_ladder(repo, "demo"), None) in seams.scans


def test_cheap_watch_orphan_blocks_the_cheap_route(tmp_path, repo, env):
    _orphan(repo / ".tp-scratch" / "cheap-watch", "handoff-abc", phase="cheap")
    seams = Seams(tmp_path)
    out = _probe(seams, repo, env)
    assert out["fallback"] == "orphan-holds-gpu"
    assert seams.leases == []


def test_design_none_scans_every_ladder_dir(tmp_path, repo, env):
    _ladder(repo, "demo").mkdir(parents=True)
    _orphan(_ladder(repo, "other-design"), "1.1", phase="1")
    seams = Seams(tmp_path)
    out = _probe(seams, repo, env, design=None)
    assert out["fallback"] == "orphan-holds-gpu"
    assert {_ladder(repo, "demo"), _ladder(repo, "other-design")} <= {d for d, _ in seams.scans}


def test_every_scan_is_phase_none_and_a_settled_orphan_does_not_block(tmp_path, repo, env):
    _orphan(_ladder(repo, "demo"), "3.1", phase="3", settled=True)
    _orphan(repo / ".tp-scratch" / "cheap-watch", "docs-1", phase="cheap",
            settled=True)
    seams = Seams(tmp_path)
    out = _probe(seams, repo, env)
    assert (out["fallback"], out["lease_state"]) == (None, "free")
    assert len(seams.leases) == 1
    assert seams.scans and all(phase is None for _, phase in seams.scans)
    assert {d for d, _ in seams.scans} >= {_ladder(repo, "demo"),
                                           repo / ".tp-scratch" / "cheap-watch"}


@pytest.mark.parametrize("window, design, measure", [
    (None, "demo", "off"),
    ("demo", "demo", "owner"),
    ("D", "demo", "other"),
    ("D", None, "other"),
])
@pytest.mark.parametrize("slot", ["docs_draft", "pr_fix_reproducer"])
def test_measure_is_the_window_role_on_every_branch(tmp_path, repo, env, window, design,
                                                    measure, slot):
    if window:
        _window(env, window)
    out = _probe(Seams(tmp_path), repo, env, slot=slot, design=design)
    assert out["measure"] == measure


def test_fail_open_scan_and_lease_errors_never_raise(tmp_path, env):
    seams = Seams(tmp_path, lease=RuntimeError("probe exploded"))

    def broken(*_a, **_kw):
        raise RuntimeError("scan exploded")

    missing = tmp_path / "not-a-repo"
    out = _shape(cheap_route.probe(SLOT, RUNG, missing, design="demo", env=env,
                                   check=seams.check, lease=seams.lease, orphans=broken))
    assert (out["route_label"], out["lease_state"], out["lease_why"]) == (
        "routed/ok", "free", "unchecked")
    assert (out["fallback"], out["lease_wait_s"]) == (None, 0.0)
