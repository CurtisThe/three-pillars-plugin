"""Tests for the release on a confirmed stop (slot-release-on-attempt-end 1.3).

`record_stop` releases the stopped agent's slot hold once when the result is settled
(`ok`/`gone`), through `attempt_orphans._release` (the module seam, like the watchdog's
`_release`): W's own agent through `attempt_release.release_once` (which records
`released` in W), a `w_reused` stop's given agent directly (no W write). The fake seam
records the ids it saw, so no test reaches the router state; `TP_LOCAL_STOPPED` stays
under `tmp_path` — never the real `~/.local/state`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pytest  # noqa: E402

import attempt_orphans as ao  # noqa: E402
import attempt_watchdog as aw  # noqa: E402
import stopped_agents  # noqa: E402

AGENT = "a0000001-w-holder"
OTHER = "b0000002-stopped"


def _w(tmp_path):
    path = tmp_path / "ladder" / "1.3.watch.json"
    aw.arm(path, attempt_id="t13", agent_id=AGENT, rung="local-medium", phase="1",
           router_log=None, now=0.0)
    return path


def _stopped_env(tmp_path, monkeypatch):
    parent = tmp_path / "tp-local"
    parent.mkdir(parents=True, exist_ok=True)
    stopped = parent / "stopped-agents.jsonl"
    monkeypatch.setenv("TP_LOCAL_STOPPED", str(stopped))
    return stopped


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake(agent_id):
        seen.append(agent_id)
        return "released"

    monkeypatch.setattr(ao, "_release", fake)
    return seen


def _state(w):
    return json.loads(Path(w).read_text(encoding="utf-8"))


@pytest.mark.parametrize("result", ["ok", "gone"])
def test_settled_stop_releases_w_agent(tmp_path, monkeypatch, calls, result):
    w = _w(tmp_path)
    _stopped_env(tmp_path, monkeypatch)
    out = ao.record_stop(w, result=result)
    assert calls == [AGENT]
    assert out["release"] == "released"
    assert out["stop_result"] == result and out["backstop"] == "written"
    rec = _state(w)["released"]
    assert rec["outcome"] == "released" and "at" in rec


@pytest.mark.parametrize("result", ["refused", "error"])
def test_unsettled_stop_never_releases(tmp_path, monkeypatch, calls, result):
    """audit c2 (impl-audit retry 2): both unsettled results on both agent paths. W's own agent
    is the owner path; a `w_reused` stop names another agent (`stopped --agent-id` after the
    next rung re-armed W). Swapping `_release_stop`'s two guard clauses (the `w_reused` check
    first) releases a possibly-still-running agent on the `w_reused` path only, so the
    other-agent call is what binds that ordering."""
    w = _w(tmp_path)
    _stopped_env(tmp_path, monkeypatch)
    out = ao.record_stop(w, result=result)
    assert calls == []
    assert "release" not in out
    assert "released" not in _state(w)
    # the same unsettled result for an agent that is not W's — the `w_reused` path
    out = ao.record_stop(w, result=result, agent_id=OTHER)
    assert out["w_reused"] is True
    assert calls == [], f"{result} stop released {calls} (W's agent {AGENT}, re-armed {OTHER})"
    assert "release" not in out
    assert "released" not in _state(w)


def test_no_backstop_still_releases(tmp_path, monkeypatch, calls):
    w = _w(tmp_path)
    _stopped_env(tmp_path, monkeypatch)
    out = ao.record_stop(w, result="ok", backstop=False)
    assert calls == [AGENT]
    assert out["release"] == "released"
    assert "backstop" not in out


def test_backstop_error_still_releases(tmp_path, monkeypatch, calls):
    w = _w(tmp_path)
    _stopped_env(tmp_path, monkeypatch)
    monkeypatch.setattr(stopped_agents, "append",
                        lambda *a, **kw: (_ for _ in ()).throw(OSError("boom")))
    out = ao.record_stop(w, result="ok")
    assert out["backstop"] == "error: boom"
    assert calls == [AGENT] and out["release"] == "released"


def test_w_reused_releases_the_given_agent_and_leaves_w(tmp_path, monkeypatch, calls):
    w = _w(tmp_path)
    _stopped_env(tmp_path, monkeypatch)
    before = w.read_text(encoding="utf-8")
    out = ao.record_stop(w, result="ok", agent_id=OTHER)
    assert calls == [OTHER]
    assert out["release"] == "released" and out["w_reused"] is True
    assert w.read_text(encoding="utf-8") == before  # the re-armed W keeps no `released`


def test_second_settled_stop_does_not_release_again(tmp_path, monkeypatch, calls):
    w = _w(tmp_path)
    _stopped_env(tmp_path, monkeypatch)
    first = ao.record_stop(w, result="ok")
    second = ao.record_stop(w, result="gone")
    assert calls == [AGENT]
    assert first["release"] == "released" and second["release"] == "already"
    assert _state(w)["released"]["outcome"] == "released"


def test_raising_seam_never_loses_the_stop_record(tmp_path, monkeypatch):
    def boom(agent_id):
        raise RuntimeError("router exploded")

    monkeypatch.setattr(ao, "_release", boom)
    w = _w(tmp_path)
    stopped = _stopped_env(tmp_path, monkeypatch)
    out = ao.record_stop(w, result="ok")
    assert out["release"] == "error: router exploded"
    state = _state(w)
    assert state["stop_result"] == "ok" and state["stop_attempts"] == 1
    line = json.loads(stopped.read_text(encoding="utf-8").splitlines()[0])
    assert line["agent"] == AGENT and line["attempt"] == "t13"
    assert (tmp_path / "ladder" / stopped_agents.LADDER_STOPS).is_file()


def test_w_reused_raising_seam_reports_error(tmp_path, monkeypatch):
    def boom(agent_id):
        raise RuntimeError("router exploded")

    monkeypatch.setattr(ao, "_release", boom)
    w = _w(tmp_path)
    _stopped_env(tmp_path, monkeypatch)
    out = ao.record_stop(w, result="gone", agent_id=OTHER)
    assert out["release"] == "error: router exploded"
    assert out["backstop"] == "written" and out["w_reused"] is True
