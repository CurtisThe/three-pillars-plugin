"""Tests for the `attempt_watchdog.py stopped` subcommand (m44-orphan-reaper 1.6).

The main thread records each stop in the state file and writes the router's
stopped-agents backstop line for every result, unless `--no-backstop`.
CLI is driven through `attempt_watchdog.main()`; `record_stop` is exercised
directly for the backstop-less path. Stdlib only, `TP_LOCAL_STOPPED` under
`tmp_path` — never the real `~/.local/state`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pytest  # noqa: E402

import attempt_orphans  # noqa: E402
import attempt_watchdog as aw  # noqa: E402

AGENT = "a0000001-rest"
AGENT8 = AGENT[:8]
ATTEMPT = "t16"


def _w(tmp_path):
    path = tmp_path / "w.watch.json"
    aw.arm(path, attempt_id=ATTEMPT, agent_id=AGENT, rung="local-medium",
           phase="1", router_log=None, now=0.0)
    return path


def _stopped_env(tmp_path, monkeypatch, parent_exists=True):
    parent = tmp_path / "tp-local"
    if parent_exists:
        parent.mkdir(parents=True, exist_ok=True)
    stopped = parent / "stopped-agents.jsonl"
    monkeypatch.setenv("TP_LOCAL_STOPPED", str(stopped))
    return stopped


def _cli(monkeypatch, argv):
    import io
    buf = io.StringIO()
    real = sys.stdout
    sys.stdout = buf
    try:
        rc = aw.main(argv)
    finally:
        sys.stdout = real
    assert rc == 0, "the CLI must exit 0"
    return json.loads(buf.getvalue())


@pytest.mark.parametrize("result", list(attempt_orphans.STOP_RESULTS))
def test_stopped_records_each_result(tmp_path, monkeypatch, result):
    w = _w(tmp_path)
    _stopped_env(tmp_path, monkeypatch)
    out = _cli(monkeypatch, ["stopped", "--state", str(w), "--result", result])
    state = json.loads(w.read_text(encoding="utf-8"))
    assert state["stop_result"] == result
    assert state["stop_attempts"] == 1
    assert out["stop_result"] == result
    assert out["backstop"] == "written"


def test_stopped_stop_attempts_increments(tmp_path, monkeypatch):
    w = _w(tmp_path)
    _stopped_env(tmp_path, monkeypatch)
    _cli(monkeypatch, ["stopped", "--state", str(w), "--result", "ok"])
    _cli(monkeypatch, ["stopped", "--state", str(w), "--result", "refused"])
    state = json.loads(w.read_text(encoding="utf-8"))
    assert state["stop_attempts"] == 2
    assert state["stop_result"] == "refused"


def test_stopped_output_keys_are_state_plus_backstop(tmp_path, monkeypatch):
    """A settled stop (1.3) adds `release` to the output and `released` to W."""
    w = _w(tmp_path)
    _stopped_env(tmp_path, monkeypatch)
    out = _cli(monkeypatch, ["stopped", "--state", str(w), "--result", "ok"])
    state = json.loads(w.read_text(encoding="utf-8"))
    assert set(out) == (set(state) - {"released"}) | {"backstop", "release"}
    assert out["release"] == "disabled"  # skills/conftest.py's TP_SLOT_RELEASE=0


def test_stopped_backstop_line_carries_agent_and_attempt(tmp_path, monkeypatch):
    w = _w(tmp_path)
    stopped = _stopped_env(tmp_path, monkeypatch)
    _cli(monkeypatch, ["stopped", "--state", str(w), "--result", "ok"])
    lines = [json.loads(line) for line in stopped.read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == 1
    assert lines[0]["agent"] == AGENT
    assert lines[0]["agent8"] == AGENT8
    assert lines[0]["attempt"] == ATTEMPT


def test_stopped_no_router_when_parent_absent(tmp_path, monkeypatch):
    w = _w(tmp_path)
    stopped = _stopped_env(tmp_path, monkeypatch, parent_exists=False)
    out = _cli(monkeypatch, ["stopped", "--state", str(w), "--result", "gone"])
    assert out["backstop"] == "no-router"
    assert not stopped.parent.exists()  # nothing created
    state = json.loads(w.read_text(encoding="utf-8"))
    assert state["stop_result"] == "gone" and state["stop_attempts"] == 1


def test_stopped_no_backstop_flag_writes_no_file(tmp_path, monkeypatch):
    w = _w(tmp_path)
    stopped = _stopped_env(tmp_path, monkeypatch)
    out = _cli(monkeypatch, ["stopped", "--state", str(w), "--result", "error",
                            "--no-backstop"])
    assert "backstop" not in out
    assert not stopped.is_file()
    state = json.loads(w.read_text(encoding="utf-8"))
    assert state["stop_result"] == "error" and state["stop_attempts"] == 1


def test_stopped_bad_result_rejected_by_argparse(tmp_path, monkeypatch):
    w = _w(tmp_path)
    _stopped_env(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        _cli(monkeypatch, ["stopped", "--state", str(w), "--result", "not-a-result"])
    assert "stop_result" not in w.read_text(encoding="utf-8")  # nothing recorded


def test_stopped_unreadable_state_is_error_json_exit_zero(tmp_path, monkeypatch):
    _stopped_env(tmp_path, monkeypatch)
    missing = tmp_path / "no" / "such.watch.json"
    out = _cli(monkeypatch, ["stopped", "--state", str(missing), "--result", "ok"])
    assert out["state"] == "error"
    assert out.get("error")
    bad = tmp_path / "bad.watch.json"
    bad.write_text("{not json", encoding="utf-8")
    out = _cli(monkeypatch, ["stopped", "--state", str(bad), "--result", "ok"])
    assert out["state"] == "error"


def test_record_stop_direct_no_backstop(tmp_path, monkeypatch):
    w = _w(tmp_path)
    stopped = _stopped_env(tmp_path, monkeypatch)
    state = attempt_orphans.record_stop(w, result="ok", backstop=False)
    assert state["stop_result"] == "ok"
    assert "backstop" not in state
    assert not stopped.is_file()


def test_record_stop_direct_written(tmp_path, monkeypatch):
    w = _w(tmp_path)
    stopped = _stopped_env(tmp_path, monkeypatch)
    state = attempt_orphans.record_stop(w, result="refused")
    assert state["backstop"] == "written"
    line = json.loads(stopped.read_text(encoding="utf-8").splitlines()[0])
    assert line["agent"] == AGENT and line["attempt"] == ATTEMPT


def test_record_stop_backstop_exception_is_error(tmp_path, monkeypatch):
    import stopped_agents
    w = _w(tmp_path)
    _stopped_env(tmp_path, monkeypatch)
    monkeypatch.setattr(stopped_agents, "append",
                        lambda *a, **kw: (_ for _ in ()).throw(OSError("boom")))
    state = attempt_orphans.record_stop(w, result="error")
    assert state["backstop"] == "error: boom"
    assert state["stop_result"] == "error"  # the stop itself still recorded


# --- audit M3: the durable per-stop record -------------------------------------

def test_stopped_writes_ladder_stops_record_even_without_router(tmp_path, monkeypatch):
    import stopped_agents
    w = _w(tmp_path)
    _stopped_env(tmp_path, monkeypatch, parent_exists=False)
    out = _cli(monkeypatch, ["stopped", "--state", str(w), "--result", "refused"])
    assert out["backstop"] == "no-router"
    rec = json.loads((tmp_path / stopped_agents.LADDER_STOPS).read_text(encoding="utf-8"))
    assert rec["agent"] == AGENT and rec["attempt"] == ATTEMPT
    assert rec["orphaned_at"] is None and rec["result"] == "refused"
    assert rec["stopped_at"] == out["stopped_at"]


def test_stopped_router_line_carries_orphaned_at_and_result(tmp_path, monkeypatch):
    import stopped_agents
    w = _w(tmp_path)
    aw.mark_orphan(w, now=42.0)
    stopped = _stopped_env(tmp_path, monkeypatch)
    _cli(monkeypatch, ["stopped", "--state", str(w), "--result", "ok", "--no-backstop"])
    _cli(monkeypatch, ["stopped", "--state", str(w), "--result", "ok"])
    line = json.loads(stopped.read_text(encoding="utf-8").splitlines()[0])
    assert line["orphaned_at"] == 42.0 and line["result"] == "ok"
    assert {"v", "agent", "agent8", "attempt", "stopped_at"} <= set(line)
    durable = (tmp_path / stopped_agents.LADDER_STOPS).read_text(encoding="utf-8").splitlines()
    assert len(durable) == 2  # --no-backstop still records the stop durably


# --- audit m1: the shared-W stop/arm race ---------------------------------------

def test_stopped_agent_id_mismatch_leaves_w_and_backstops_the_given_agent(tmp_path, monkeypatch):
    """The next rung re-armed W before the stop landed: `--agent-id` names the
    stopped agent, so W (another attempt's now) is untouched."""
    import stopped_agents
    w = _w(tmp_path)
    before = w.read_text(encoding="utf-8")
    stopped = _stopped_env(tmp_path, monkeypatch)
    out = _cli(monkeypatch, ["stopped", "--state", str(w), "--agent-id", "b0000002-old",
                            "--result", "refused"])
    assert w.read_text(encoding="utf-8") == before
    assert out["w_reused"] is True and out["backstop"] == "written"
    assert out["agent_id"] == "b0000002-old" and out["stop_result"] == "refused"
    line = json.loads(stopped.read_text(encoding="utf-8").splitlines()[0])
    assert line["agent"] == "b0000002-old" and line["agent8"] == "b0000002"
    durable = json.loads((tmp_path / stopped_agents.LADDER_STOPS).read_text(encoding="utf-8"))
    assert durable["agent"] == "b0000002-old" and durable["result"] == "refused"


def test_stopped_agent_id_match_records_into_w(tmp_path, monkeypatch):
    w = _w(tmp_path)
    _stopped_env(tmp_path, monkeypatch)
    out = _cli(monkeypatch, ["stopped", "--state", str(w), "--agent-id", AGENT,
                            "--result", "ok"])
    state = json.loads(w.read_text(encoding="utf-8"))
    assert "w_reused" not in out and state["stop_result"] == "ok"
    assert set(out) == (set(state) - {"released"}) | {"backstop", "release"}


def test_stopped_agent_id_with_w_already_swept_still_backstops(tmp_path, monkeypatch):
    stopped = _stopped_env(tmp_path, monkeypatch)
    gone = tmp_path / "gone.watch.json"
    out = _cli(monkeypatch, ["stopped", "--state", str(gone), "--agent-id", AGENT,
                            "--result", "gone"])
    assert out["w_reused"] is True and out["backstop"] == "written"
    assert not gone.exists() and stopped.is_file()
