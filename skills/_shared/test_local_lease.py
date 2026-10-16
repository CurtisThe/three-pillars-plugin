"""test_local_lease.py — the local-rung slot check (operator ruling Q1).

design: local-implement-and-review; run-throughput (Q1)

``acquire`` asks the router's own slot owner, through its public side-traffic probe,
whether ANOTHER conversation holds the local slot: busy → exit 3 (the rung becomes
``unavailable`` / ``local-busy``); free or held by this session → exit 0; no router
install → ``unchecked``, exit 0. Fixture slot-owner files drive a stub module that only
answers the probe the way ``bin/slot_owner.py`` documents; when the real local-llm-skills
install is on PATH the same fixtures run through the real module too.
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
EP = "http://127.0.0.1:11434"
ME, OTHER = "5e55a0a1-mine-session", "0b0e0b0e-other-session"


@pytest.fixture(autouse=True)
def _no_live_measure_window(tmp_path, monkeypatch):
    """Keep an operator's live measure window out of these slot tests (in-process and CLI)."""
    monkeypatch.setattr(local_lease.measure_window, "load", lambda env: None)
    monkeypatch.setenv("TP_LOCAL_LOG", str(tmp_path / "tp-local" / "router.log"))


class _Stub:
    """``SlotOwner`` as the router documents it: side traffic sees ``unowned`` when the
    slot is free (no owner, or idle past ``idle_s`` with nothing in flight), else
    ``slot held by <id8>``."""

    def __init__(self, state_path, idle_s=120.0):
        self.state_path, self.idle_s = str(state_path), idle_s

    def acquire(self, endpoint, key, *, subagent):
        assert subagent is False and key  # the probe is side traffic, never a taker
        slot = json.loads(Path(self.state_path).read_text(encoding="utf-8")).get(endpoint) or {}
        owner = slot.get("owner_key")
        idle = not slot.get("in_flight") and (
            slot.get("last_seen") is None or time.time() - slot["last_seen"] >= self.idle_s)
        return ((endpoint, None), "unowned") if owner is None or idle else (
            None, f"slot held by {owner[:8]}")


def _state(tmp_path, owner, *, age_s=5.0, in_flight=None) -> Path:
    path = tmp_path / "slot-owner.json"
    path.write_text(json.dumps({EP: {"owner_key": owner, "in_flight": in_flight or {},
                                     "last_seen": time.time() - age_s}}), encoding="utf-8")
    return path


def _stub_module(state_path):
    return type("M", (), {"SlotOwner": lambda self=None: _Stub(state_path)})


@pytest.mark.parametrize("owner,age,want", [
    (OTHER, 5.0, "busy"), (OTHER, 900.0, "free"), (ME, 5.0, "free"), (None, 5.0, "free")])
def test_acquire_reads_the_owner_from_a_fixture_slot_file(tmp_path, owner, age, want):
    mod = _stub_module(_state(tmp_path, owner, age_s=age))
    state, why = local_lease.acquire(env={"CLAUDE_CODE_SESSION_ID": ME}, module=mod)
    assert state == want, why
    if want == "busy":
        assert why == f"slot held by {OTHER[:8]}"


def test_no_router_install_is_unchecked_never_busy():
    state, why = local_lease.acquire(env={}, which=lambda _name: None)
    assert (state, why) == ("unchecked", "no local router install (tp-local / slot_owner.py)")


def test_cli_busy_exits_3_through_a_fixture_install(tmp_path):
    """The CLI end to end: a fake `tp-local` whose sibling slot_owner.py is the stub."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "tp-local").write_text("#!/bin/sh\n", encoding="utf-8")
    (bin_dir / "tp-local").chmod(0o755)
    state = _state(tmp_path, OTHER)
    (bin_dir / "slot_owner.py").write_text(
        "import json, time\n"
        f"STATE = {str(state)!r}\n"
        "class SlotOwner:\n"
        "    state_path = STATE\n"
        "    def acquire(self, ep, key, *, subagent):\n"
        "        o = json.load(open(STATE))[ep]['owner_key']\n"
        "        return None, 'slot held by ' + o[:8]\n", encoding="utf-8")
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
           "CLAUDE_CODE_SESSION_ID": ME}
    res = subprocess.run([sys.executable, str(SCRIPT), "acquire"], capture_output=True,
                         text=True, env=env, timeout=30)
    assert (res.returncode, res.stdout.strip()) == (3, f"lease: busy (slot held by {OTHER[:8]})")
    res = subprocess.run([sys.executable, str(SCRIPT), "release"], capture_output=True,
                         text=True, env=env, timeout=30)
    assert (res.returncode, res.stdout.strip()) == (0, "lease: released")


@pytest.mark.skipif(shutil.which("tp-local") is None or local_lease.slot_owner_module() is None,
                    reason="local-llm-skills router not installed")
@pytest.mark.parametrize("owner,age,want", [(OTHER, 5.0, "busy"), (ME, 5.0, "free"),
                                           (OTHER, 900.0, "free")])
def test_real_router_slot_owner_on_fixture_state(tmp_path, monkeypatch, owner, age, want):
    monkeypatch.setenv("TP_LOCAL_SLOT_STATE", str(_state(tmp_path, owner, age_s=age)))
    state, why = local_lease.acquire(env={"CLAUDE_CODE_SESSION_ID": ME})
    assert state == want, why


def test_bare_release_stays_id_less_and_never_loads_the_router(monkeypatch, capsys):
    """design: slot-release-on-attempt-end — ``release`` without ``--agent-id`` is still a no-op.

    Only the id-carrying form (``release --agent-id X``, test_local_lease_release.py) reaches
    the router; the spawn-failed exit paths in the dispatch docs stay id-less on purpose.
    """
    def _loader(which=shutil.which):
        raise AssertionError("an id-less release must not load the router module")

    monkeypatch.setattr(local_lease, "slot_owner_module", _loader)
    assert local_lease.main(["release"]) == 0
    assert capsys.readouterr().out.strip() == "lease: released"


def test_resolve_endpoint_unchanged():
    assert local_lease.resolve_endpoint("E", {"ANTHROPIC_BASE_URL": "http://x"}) == "E"
    assert local_lease.resolve_endpoint(None, {"ANTHROPIC_BASE_URL": "http://x"}) == "http://x"
    assert local_lease.resolve_endpoint(None, {}) == "default"
