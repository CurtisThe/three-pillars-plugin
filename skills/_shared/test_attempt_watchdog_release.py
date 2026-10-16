"""Tests for the watchdog's release-once-on-`done` step (slot-release-on-attempt-end 1.2).

`poll` is driven with `verdict` monkeypatched to a fixed dict and `aw._release` (the module
seam, like `_sleep`) replaced by a fake, so no test ever reaches the live router state.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pytest  # noqa: E402

import attempt_watchdog as aw  # noqa: E402
import local_lease  # noqa: E402

AGENT = "agent-one-full-id"


def _verdict(state_name):
    return lambda *a, **k: {"state": state_name, "reason": "", "flags": []}


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(aw, "_sleep", lambda s: None)
    monkeypatch.setenv("TP_LOCAL_LOG", str(tmp_path / "absent.log"))


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake(agent_id):
        seen.append(agent_id)
        return "released"

    monkeypatch.setattr(aw, "_release", fake)
    return seen


@pytest.fixture
def w(tmp_path):
    path = tmp_path / "ladder" / "1.2.watch.json"
    aw.arm(path, attempt_id="t", agent_id=AGENT, rung="local-medium", phase="1",
           router_log=None, now=0.0)
    return path


def _poll(w, tmp_path, **kw):
    t = tmp_path / "agent.jsonl"
    t.write_text("{}\n", encoding="utf-8")
    return aw.poll(w, transcript=t, for_s=0, now=10.0,
                   capability_path=tmp_path / "nocap.json", **kw)


def _state(w):
    return json.loads(Path(w).read_text(encoding="utf-8"))


@pytest.mark.parametrize("finished", [False, True])
def test_done_releases_once_and_records(monkeypatch, tmp_path, w, calls, finished):
    monkeypatch.setattr(aw, "verdict", _verdict("done"))
    out = _poll(w, tmp_path, finished=finished)
    assert out["state"] == "done"
    assert calls == [AGENT]
    assert out["release"] == "released"
    released = _state(w)["released"]
    assert released["outcome"] == "released"
    assert "at" in released


@pytest.mark.parametrize("finished", [False, True])
def test_second_poll_does_not_release_again(monkeypatch, tmp_path, w, calls, finished):
    monkeypatch.setattr(aw, "verdict", _verdict("done"))
    _poll(w, tmp_path, finished=finished)
    again = _poll(w, tmp_path, finished=finished)
    assert again["state"] == "done"
    assert again["release"] == "already"
    assert calls == [AGENT]


@pytest.mark.parametrize("state_name", ["running", "runaway"])
def test_running_and_runaway_never_release(monkeypatch, tmp_path, w, calls, state_name):
    monkeypatch.setattr(aw, "verdict", _verdict(state_name))
    out = _poll(w, tmp_path)
    assert out["state"] == state_name
    assert "release" not in out
    assert calls == []
    assert "released" not in _state(w)


def test_unreadable_state_never_releases(monkeypatch, tmp_path, w, calls):
    monkeypatch.setattr(aw, "verdict", _verdict("done"))
    w.write_text("not json {", encoding="utf-8")
    out = _poll(w, tmp_path)
    assert out["state"] == "error"
    assert "release" not in out
    assert calls == []


def test_raising_seam_reports_error_and_keeps_verdict(monkeypatch, tmp_path, w):
    monkeypatch.setattr(aw, "verdict", _verdict("done"))

    def boom(agent_id):
        raise RuntimeError("router exploded")

    monkeypatch.setattr(aw, "_release", boom)
    out = _poll(w, tmp_path)
    assert out["state"] == "done"
    assert out["reason"] == ""
    assert out["release"].startswith("error: ")
    assert "router exploded" in out["release"]


def test_rearmed_agent_releases_once_more(monkeypatch, tmp_path, w, calls):
    monkeypatch.setattr(aw, "verdict", _verdict("done"))
    _poll(w, tmp_path)
    aw.arm(w, attempt_id="t", agent_id="agent-two", rung="local-medium", phase="1",
           router_log=None, now=20.0)
    assert "released" not in _state(w)
    out = _poll(w, tmp_path)
    assert out["release"] == "released"
    assert calls == [AGENT, "agent-two"]
    assert _state(w)["agent_id"] == "agent-two"
    assert _poll(w, tmp_path)["release"] == "already"
    assert calls == [AGENT, "agent-two"]


def test_rearm_between_read_and_write_keeps_the_new_agent(monkeypatch, tmp_path, w):
    monkeypatch.setattr(aw, "verdict", _verdict("done"))
    seen = []

    def rearm_then_release(agent_id):
        seen.append(agent_id)
        aw.arm(w, attempt_id="t", agent_id="agent-two", rung="local-medium", phase="1",
               router_log=None, now=20.0)
        return "released"

    monkeypatch.setattr(aw, "_release", rearm_then_release)
    out = _poll(w, tmp_path)
    assert out["release"] == "released"
    assert seen == [AGENT]
    state = _state(w)
    assert state["agent_id"] == "agent-two"
    assert "released" not in state


def test_default_seam_is_disabled_under_the_test_env(monkeypatch, tmp_path, w):
    """No monkeypatched `_release`: TP_SLOT_RELEASE=0 answers `disabled`. The shipped
    `skills/conftest.py` sets it for every test; it is set here too, as this guard's own input.

    audit c3 (impl-audit retry 1): `disabled` alone also answers when the router module is
    loaded first, so the guard binds on the ordering claim — the switch is checked before
    any router load, hence `slot_owner_module` is never reached.
    """
    loads = []

    def no_load(*args, **kw):
        loads.append(args)
        raise AssertionError("the switch must be checked before any router load")

    monkeypatch.setenv("TP_SLOT_RELEASE", "0")
    monkeypatch.setattr(local_lease, "slot_owner_module", no_load)
    monkeypatch.setattr(aw, "verdict", _verdict("done"))
    out = _poll(w, tmp_path)
    assert out["release"] == "disabled"
    assert _state(w)["released"]["outcome"] == "disabled"
    assert loads == []
