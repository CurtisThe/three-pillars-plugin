"""Tests for attempt_reaper.py — the main-thread watch loop.

m44-orphan-reaper task 2.1: `watch` hands back reapable orphans at once
(orphan-marked, `stop_result` not `ok`/`gone`, below the stop cap), returns on
the worker's transcript end of turn once no armed attempt still runs (audit M1),
or runs out at `for_s` clamped to
`MAX_WATCH_S` (7000 — one background Bash call under its 7,200 s cap; seat
ruling 2026-10-02, not `attempt_watchdog.MAX_FOR_S`). A settled stop or a
stop-at-cap never reaps: the loop just runs out. Injected clock/sleep keep the
loop hermetic; no `claude`, no network.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pytest  # noqa: E402

import attempt_reaper as ar  # noqa: E402

CASES = json.loads((HERE / "fixtures" / "transcript_tail" / "tails.json").read_text(encoding="utf-8"))["cases"]
AGENT = "a0000001"
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


def _clock_sleep(start: float = 0.0, mutate_after_sleep=None):
    """A clock that advances by whatever `sleep` is asked, with a call log."""
    t = [start]
    sleeps: list[float] = []

    def clock() -> float:
        return t[0]

    def sleep(s: float) -> None:
        sleeps.append(s)
        t[0] += s
        if mutate_after_sleep is not None:
            mutate_after_sleep()

    return clock, sleep, sleeps


# --- reapable orphans ---------------------------------------------------------

def test_watch_reaps_orphan_without_stop_record_at_once(tmp_path):
    lad = _lad(tmp_path)
    f = _state_file(lad, "1", {"attempt_id": "2.1", "agent_id": AGENT, "orphan": True})
    clock, sleep, sleeps = _clock_sleep()
    out = ar.watch(lad, for_s=3600, interval_s=15, clock=clock, sleep=sleep)
    assert out == {"reap": [{"state": str(f), "attempt_id": "2.1", "agent_id": AGENT,
                             "why": "orphan"}],
                   "worker_done": False, "for_s": 3600}
    assert sleeps == []  # hands back at once; never loops


@pytest.mark.parametrize("result", ["refused", "error"])
def test_watch_still_reaps_refused_or_error_record(tmp_path, result):
    lad = _lad(tmp_path)
    f = _state_file(lad, "1", {"attempt_id": "2.1", "agent_id": AGENT, "orphan": True,
                               "stop_result": result, "stop_attempts": 1})
    out = ar.watch(lad, for_s=0)
    assert [r["state"] for r in out["reap"]] == [str(f)]
    assert out["reap"][0]["why"] == "orphan" and out["worker_done"] is False


@pytest.mark.parametrize("state", [
    {"attempt_id": "a", "agent_id": AGENT, "orphan": True, "stop_result": "ok", "stop_attempts": 1},
    {"attempt_id": "b", "agent_id": AGENT, "orphan": True, "stop_result": "gone", "stop_attempts": 1},
    {"attempt_id": "c", "agent_id": AGENT, "orphan": True, "stop_result": "error",
     "stop_attempts": ar.MAX_STOP_ATTEMPTS},
    {"attempt_id": "d", "agent_id": AGENT, "orphan": False},
])
def test_watch_skips_settled_capped_and_non_orphans(tmp_path, state):
    lad = _lad(tmp_path)
    _state_file(lad, "1", state)
    clock, sleep, sleeps = _clock_sleep()
    out = ar.watch(lad, for_s=0, clock=clock, sleep=sleep)
    assert out["reap"] == [] and out["worker_done"] is False and sleeps == []


def test_watch_skips_unreadable_state_files(tmp_path):
    lad = _lad(tmp_path)
    (lad / "bad.watch.json").write_text("{not json", encoding="utf-8")
    (lad / "list.watch.json").write_text(json.dumps([1, 2]) + "\n", encoding="utf-8")
    good = _state_file(lad, "good", {"attempt_id": "2.1", "agent_id": AGENT, "orphan": True})
    out = ar.watch(lad, for_s=0)
    assert [r["state"] for r in out["reap"]] == [str(good)]


def test_watch_missing_ladder_dir_is_empty(tmp_path):
    out = ar.watch(tmp_path / "no" / "such", for_s=0)
    assert out == {"reap": [], "worker_done": False, "for_s": 0}


def test_watch_picks_up_orphan_appearing_during_watch(tmp_path):
    lad = _lad(tmp_path)
    _state_file(lad, "settled", {"attempt_id": "x", "agent_id": AGENT, "orphan": True,
                                 "stop_result": "ok", "stop_attempts": 1})

    def appear() -> None:
        _state_file(lad, "late", {"attempt_id": "2.9", "agent_id": AGENT, "orphan": True})

    clock, sleep, sleeps = _clock_sleep(mutate_after_sleep=appear)
    out = ar.watch(lad, for_s=60, interval_s=15, clock=clock, sleep=sleep)
    assert [r["attempt_id"] for r in out["reap"]] == ["2.9"]
    assert sleeps == [15]  # one idle round, then the reap target ends the loop


# --- worker done --------------------------------------------------------------

def test_watch_worker_done_on_end_of_turn_with_nothing_running(tmp_path):
    cfg = _cfg_agent(tmp_path, "end_turn_trailing", WORKER)
    lad = _lad(tmp_path)
    clock, sleep, sleeps = _clock_sleep()
    out = ar.watch(lad, worker_agent_id=WORKER, config_dir=cfg, for_s=3600, clock=clock, sleep=sleep)
    assert out["worker_done"] is True and out["reap"] == [] and sleeps == []


def test_watch_worker_end_of_turn_with_armed_running_attempt_keeps_watching(tmp_path):
    """Audit M1: a tp-worker ends its turn while its nested attempt runs in the
    background, so end of turn alone is not `worker_done`."""
    cfg = _cfg_agent(tmp_path, "end_turn_trailing", WORKER)
    _cfg_agent(tmp_path, "mid_tool_call", AGENT)
    lad = _lad(tmp_path)
    _state_file(lad, "1", {"attempt_id": "2.1", "agent_id": AGENT, "orphan": False})
    clock, sleep, sleeps = _clock_sleep()
    out = ar.watch(lad, worker_agent_id=WORKER, config_dir=cfg, for_s=45, interval_s=15,
                   clock=clock, sleep=sleep)
    assert out == {"reap": [], "worker_done": False, "for_s": 45}
    assert sleeps == [15, 15, 15]  # no early return: it ran the budget out


def test_watch_worker_done_once_armed_attempt_ended(tmp_path):
    cfg = _cfg_agent(tmp_path, "end_turn_trailing", WORKER)
    _cfg_agent(tmp_path, "end_turn_trailing", AGENT)
    lad = _lad(tmp_path)
    _state_file(lad, "1", {"attempt_id": "2.1", "agent_id": AGENT, "orphan": False})
    out = ar.watch(lad, worker_agent_id=WORKER, config_dir=cfg, for_s=3600)
    assert out == {"reap": [], "worker_done": True, "for_s": 3600}


def test_watch_worker_done_not_masked_by_settled_orphan(tmp_path):
    cfg = _cfg_agent(tmp_path, "end_turn_trailing", WORKER)
    lad = _lad(tmp_path)
    _state_file(lad, "1", {"attempt_id": "2.1", "agent_id": AGENT, "orphan": True,
                           "stop_result": "ok", "stop_attempts": 1})
    out = ar.watch(lad, worker_agent_id=WORKER, config_dir=cfg, for_s=0)
    assert out == {"reap": [], "worker_done": True, "for_s": 0}


def test_watch_worker_mid_turn_is_not_done(tmp_path):
    cfg = _cfg_agent(tmp_path, "mid_tool_call", WORKER)
    lad = _lad(tmp_path)
    out = ar.watch(lad, worker_agent_id=WORKER, config_dir=cfg, for_s=0)
    assert out["worker_done"] is False and out["reap"] == []


def test_watch_worker_without_transcript_is_not_done(tmp_path):
    lad = _lad(tmp_path)
    out = ar.watch(lad, worker_agent_id=WORKER, config_dir=tmp_path, for_s=0)
    assert out["worker_done"] is False


# --- for_s clamp and run-out --------------------------------------------------

def test_watch_for_s_clamped_to_max_watch_s(tmp_path):
    lad = _lad(tmp_path)
    _state_file(lad, "1", {"attempt_id": "a", "agent_id": AGENT, "orphan": True,
                           "stop_result": "ok", "stop_attempts": 1})
    clock, sleep, _ = _clock_sleep()
    out = ar.watch(lad, for_s=999_999, interval_s=15, clock=clock, sleep=sleep)
    assert out["for_s"] == ar.MAX_WATCH_S == 7000
    assert out["reap"] == []


def test_watch_settled_stop_never_reaps_and_runs_out(tmp_path):
    lad = _lad(tmp_path)
    _state_file(lad, "1", {"attempt_id": "2.1", "agent_id": AGENT, "orphan": True,
                           "stop_result": "refused", "stop_attempts": ar.MAX_STOP_ATTEMPTS})
    clock, sleep, sleeps = _clock_sleep()
    out = ar.watch(lad, for_s=45, interval_s=15, clock=clock, sleep=sleep)
    assert out == {"reap": [], "worker_done": False, "for_s": 45}
    assert sleeps == [15, 15, 15]  # loops until for_s, never on the settled stop


# --- one end-of-turn helper (audit m4) ------------------------------------------

def test_watch_and_sweep_share_attempt_orphans_agent_ended(tmp_path, monkeypatch):
    import attempt_orphans
    seen: list[str] = []

    def fake(agent_id, config_dir=None):
        seen.append(agent_id)
        return True

    monkeypatch.setattr(attempt_orphans, "agent_ended", fake)
    lad = _lad(tmp_path)
    _state_file(lad, "1", {"attempt_id": "2.1", "agent_id": AGENT, "orphan": False})
    assert ar.watch(lad, worker_agent_id=WORKER, for_s=0)["worker_done"] is True
    assert ar.sweep(lad)["reap"] == []
    assert WORKER in seen and AGENT in seen
    assert not hasattr(ar, "_ended") and not hasattr(ar, "_worker_done")
    assert attempt_orphans.orphan_finished({"agent_id": AGENT}) is True
