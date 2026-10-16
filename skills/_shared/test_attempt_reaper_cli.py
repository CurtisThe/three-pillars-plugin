"""Tests for attempt_reaper.py — task 2.2: `sweep` and the one-line JSON CLI.

`sweep` lists every armed, still-running, reapable attempt (orphan or not,
`why: "armed-running"`) and filters by `phase`; `reapable` follows the design's
orphan-agnostic rule. The CLI `watch` / `sweep` prints exactly one JSON line
and exits 0 (missing dir → `{"reap": []}`); neither command stops anything.
CLI tests call `main([...])` in-process (capsys) with `--for 0` so nothing
sleeps; one subprocess smoke of `sweep` on a missing dir. No `claude`, no
network.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pytest  # noqa: E402

import attempt_reaper as ar  # noqa: E402

CASES = json.loads((HERE / "fixtures" / "transcript_tail" / "tails.json").read_text(encoding="utf-8"))["cases"]
AGENT = "a0000001"
OTHER = "a0000002"
WORKER = "w9876543"
LADDER = "ladder"


def _lad(tmp_path: Path) -> Path:
    lad = tmp_path / LADDER
    lad.mkdir(parents=True, exist_ok=True)
    return lad


def _state_file(lad: Path, name: str, state: dict) -> Path:
    p = lad / f"{name}.watch.json"
    p.write_text(json.dumps(state) + "\n", encoding="utf-8")
    return p


def _cfg_agent(tmp_path: Path, case: str, agent: str) -> Path:
    """The located transcript at `<config_dir>/projects/*/*/subagents/agent-<agent>.jsonl`."""
    sub = tmp_path / "projects" / "proj" / "sess" / "subagents"
    sub.mkdir(parents=True, exist_ok=True)
    (sub / f"agent-{agent}.jsonl").write_text(
        "\n".join(json.dumps(r) for r in CASES[case]) + "\n", encoding="utf-8")
    return tmp_path


def _one_json(capsys) -> dict:
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(lines) == 1
    return json.loads(lines[0])


# --- reapable (design rule: orphan-agnostic) ----------------------------------

def test_reapable_non_orphan_without_stop_record():
    assert ar.reapable({"agent_id": AGENT}) is True
    assert ar.reapable({"agent_id": AGENT, "orphan": False}) is True


@pytest.mark.parametrize("state", [
    {"stop_result": "ok", "stop_attempts": 1},
    {"stop_result": "gone", "stop_attempts": 1},
    {"stop_result": "error", "stop_attempts": ar.MAX_STOP_ATTEMPTS},
])
def test_reapable_settled_or_capped_is_not_reapable(state):
    assert ar.reapable({"agent_id": AGENT, "orphan": False, **state}) is False


# --- sweep --------------------------------------------------------------------

def test_sweep_lists_armed_running_orphan_or_not(tmp_path):
    cfg = _cfg_agent(tmp_path, "mid_tool_call", AGENT)
    _cfg_agent(tmp_path, "mid_tool_call", OTHER)
    lad = _lad(tmp_path)
    f1 = _state_file(lad, "1", {"attempt_id": "2.1", "agent_id": AGENT, "orphan": True})
    f2 = _state_file(lad, "2", {"attempt_id": "2.2", "agent_id": OTHER, "orphan": False})
    assert ar.sweep(lad, config_dir=cfg) == {"reap": [
        {"state": str(f1), "attempt_id": "2.1", "agent_id": AGENT, "why": "armed-running"},
        {"state": str(f2), "attempt_id": "2.2", "agent_id": OTHER, "why": "armed-running"},
    ]}


def test_sweep_missing_transcript_counts_as_running(tmp_path):
    lad = _lad(tmp_path)
    f = _state_file(lad, "1", {"attempt_id": "2.1", "agent_id": AGENT, "orphan": False})
    out = ar.sweep(lad, config_dir=tmp_path)  # empty config dir: no transcript
    assert out == {"reap": [{"state": str(f), "attempt_id": "2.1",
                             "agent_id": AGENT, "why": "armed-running"}]}


def test_sweep_skips_ended_transcript(tmp_path):
    cfg = _cfg_agent(tmp_path, "end_turn_trailing", AGENT)
    lad = _lad(tmp_path)
    _state_file(lad, "1", {"attempt_id": "2.1", "agent_id": AGENT, "orphan": True})
    assert ar.sweep(lad, config_dir=cfg) == {"reap": []}


def test_sweep_filters_phase_str_compared(tmp_path):
    cfg = _cfg_agent(tmp_path, "mid_tool_call", AGENT)
    lad = _lad(tmp_path)
    f1 = _state_file(lad, "1", {"attempt_id": "a", "agent_id": AGENT, "phase": 1})
    f2 = _state_file(lad, "2", {"attempt_id": "b", "agent_id": AGENT, "phase": 2})
    assert [r["state"] for r in ar.sweep(lad, phase=2, config_dir=cfg)["reap"]] == [str(f2)]
    assert [r["state"] for r in ar.sweep(lad, phase="2", config_dir=cfg)["reap"]] == [str(f2)]
    assert len(ar.sweep(lad, config_dir=cfg)["reap"]) == 2


@pytest.mark.parametrize("state", [
    {"attempt_id": "a", "agent_id": AGENT, "stop_result": "ok", "stop_attempts": 1},
    {"attempt_id": "b", "agent_id": AGENT, "stop_result": "gone", "stop_attempts": 1},
    {"attempt_id": "c", "agent_id": AGENT, "stop_result": "error",
     "stop_attempts": ar.MAX_STOP_ATTEMPTS},
    {"attempt_id": "d"},  # not armed: no agent_id
])
def test_sweep_skips_not_reapable_or_not_armed(tmp_path, state):
    lad = _lad(tmp_path)
    _state_file(lad, "1", state)
    assert ar.sweep(lad, config_dir=tmp_path) == {"reap": []}


def test_sweep_missing_dir_and_unreadable_states(tmp_path):
    assert ar.sweep(tmp_path / "no" / "such", config_dir=tmp_path) == {"reap": []}
    lad = _lad(tmp_path)
    (lad / "bad.watch.json").write_text("{not json", encoding="utf-8")
    (lad / "list.watch.json").write_text(json.dumps([1]) + "\n", encoding="utf-8")
    assert ar.sweep(lad, config_dir=tmp_path) == {"reap": []}


# --- CLI: one JSON line, exit 0 ------------------------------------------------

def test_cli_watch_one_json_line_exit_0(tmp_path, capsys):
    cfg = _cfg_agent(tmp_path, "end_turn_trailing", WORKER)
    lad = _lad(tmp_path)
    f = _state_file(lad, "1", {"attempt_id": "2.1", "agent_id": AGENT, "orphan": True})
    rc = ar.main(["watch", "--dir", str(lad), "--worker-agent-id", WORKER,
                  "--config-dir", str(cfg), "--for", "0", "--interval", "15"])
    out = _one_json(capsys)
    assert rc == 0
    assert out["reap"] == [{"state": str(f), "attempt_id": "2.1",
                            "agent_id": AGENT, "why": "orphan"}]
    # the worker is at end of turn, but its armed orphan still runs (audit M1)
    assert out["worker_done"] is False


def test_cli_sweep_one_json_line_exit_0(tmp_path, capsys):
    lad = _lad(tmp_path)
    f = _state_file(lad, "1", {"attempt_id": "2.1", "agent_id": AGENT,
                               "orphan": False, "phase": 2})
    rc = ar.main(["sweep", "--dir", str(lad), "--phase", "2", "--config-dir", str(tmp_path)])
    out = _one_json(capsys)
    assert rc == 0
    assert out == {"reap": [{"state": str(f), "attempt_id": "2.1",
                             "agent_id": AGENT, "why": "armed-running"}]}


def test_cli_sweep_missing_dir_is_empty(tmp_path, capsys):
    rc = ar.main(["sweep", "--dir", str(tmp_path / "no" / "such")])
    assert rc == 0 and _one_json(capsys) == {"reap": []}


def test_cli_fail_open_prints_error_json_and_exit_0(tmp_path, capsys, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(ar, "sweep", boom)
    rc = ar.main(["sweep", "--dir", str(tmp_path)])
    assert rc == 0 and _one_json(capsys) == {"reap": [], "error": "boom"}


def test_cli_sweep_subprocess_missing_dir(tmp_path):
    res = subprocess.run(
        [sys.executable, str(HERE / "attempt_reaper.py"), "sweep",
         "--dir", str(tmp_path / "no" / "such")],
        capture_output=True, text=True, check=True)
    assert res.returncode == 0
    assert [ln for ln in res.stdout.splitlines() if ln.strip()] == [json.dumps({"reap": []})]
