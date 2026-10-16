"""Tests for attempt_watchdog.py — poll, orphans, the CLI and the capability-stale
flag, plus the finished wall-clock breach (run-throughput 1.6).

`poll` and `orphans` are exercised directly with injected `now` and `clock` seams
(no sleeping); the CLI is driven through `attempt_watchdog.main()` with a patched
`_clock` so no real time elapses. The finished wall-clock breach is the gap the
dispatcher found in 1.5's `verdict`: a finished attempt whose final turn is past the
budget is `runaway`, not `done`.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pytest  # noqa: E402

import attempt_watchdog as aw  # noqa: E402
import router_stats as rs  # noqa: E402
import wait_budget  # noqa: E402

BUNDLES = json.loads((HERE / "fixtures" / "attempt_watchdog" / "breach.json").read_text(encoding="utf-8"))
CASES = json.loads((HERE / "fixtures" / "transcript_tail" / "tails.json").read_text(encoding="utf-8"))["cases"]
AGENT = "a0000001-rest-of-id"
AGENT8 = AGENT[:8]
CFG = {"attempt_wall_clock_s": 1000}


def _state(tmp_path, started_at, phase="1"):
    path = tmp_path / "ladder" / "1.6.watch.json"
    state = aw.arm(path, attempt_id="t16", agent_id=AGENT, rung="local-medium",
                   phase=phase, router_log=None, now=started_at)
    return json.loads(json.dumps(state)), path


def _transcript(tmp_path, case):
    path = tmp_path / "agent.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in CASES[case]) + "\n", encoding="utf-8")
    return path


def _cap(path, version):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"claude_code_version": version}), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _hermetic(tmp_path, monkeypatch):
    """No real sleeping and no real router log: `_sleep` records, TP_LOCAL_LOG is absent."""
    slept = []
    monkeypatch.setattr(aw, "_sleep", slept.append)
    monkeypatch.setenv("TP_LOCAL_LOG", str(tmp_path / "absent-router.log"))
    return slept


def _clock(monkeypatch, value):
    def fake_clock():
        return value

    monkeypatch.setattr(aw, "_clock", fake_clock)


FINAL_EPOCH = datetime.fromisoformat("2026-09-28T15:00:18.400Z".replace("Z", "+00:00")).timestamp()


# --- verdict: the finished wall-clock breach (1.5 gap) --------------------------

def test_finished_final_turn_past_budget_is_runaway(tmp_path):
    start = FINAL_EPOCH - 1000.0  # the fixture's final turn is 1000s after arm == budget
    state, _ = _state(tmp_path, start)
    out = aw.verdict(state, _transcript(tmp_path, "end_turn_trailing"), [], CFG,
                     now=FINAL_EPOCH + 1_000_000.0, finished=True)
    assert out["state"] == "runaway"
    assert out["reason"] == "runaway: wall-clock 1000s ≥ 1000s"


def test_finished_final_turn_under_budget_is_done(tmp_path):
    start = FINAL_EPOCH - 100.0  # 100s after arm < 1000s budget
    state, _ = _state(tmp_path, start)
    out = aw.verdict(state, _transcript(tmp_path, "end_turn_trailing"), [], CFG,
                     now=FINAL_EPOCH + 1_000_000.0, finished=True)
    assert out["state"] == "done" and out["reason"] == ""
    assert out["reply_text"] == '{"claimed": "done"}'


# --- poll: one read, capability-stale flag --------------------------------------

def test_poll_for_zero_is_one_verdict(tmp_path, monkeypatch):
    state, path = _state(tmp_path, 0.0)
    calls = []
    real_verdict = aw.verdict

    def spy(*a, **kw):
        calls.append(a)
        return real_verdict(*a, **kw)

    monkeypatch.setattr(aw, "verdict", spy)
    t = _transcript(tmp_path, "mid_tool_call")
    out = aw.poll(path, transcript=t, for_s=0, now=10.0)
    assert out["state"] == "running"
    assert len(calls) == 1
    assert calls[0][0] == state  # poll re-reads the state dict from disk
    assert calls[0][1] == t


def test_poll_finished_reads_once(tmp_path, monkeypatch):
    state, path = _state(tmp_path, 0.0)
    calls = []
    real_verdict = aw.verdict

    def spy(*a, **kw):
        calls.append(a)
        return real_verdict(*a, **kw)

    monkeypatch.setattr(aw, "verdict", spy)
    t = _transcript(tmp_path, "mid_tool_call")
    out = aw.poll(path, transcript=t, finished=True, now=999_999.0)
    assert out["state"] == "done"
    assert "watchdog-no-end-turn" in out["flags"]
    assert len(calls) == 1
    assert calls[0][0] == state  # poll re-reads the state dict from disk


def test_poll_adds_capability_stale_flag(tmp_path, monkeypatch):
    _, sp = _state(tmp_path, 0.0)
    t = _transcript(tmp_path, "mid_tool_call")
    cap = _cap(tmp_path / "runaway_capability.json", "2.1.282")
    out = aw.poll(sp, transcript=t, for_s=0, now=10.0, capability_path=cap)
    assert "capability-stale 2.1.282->2.1.283" in out["flags"]


def test_poll_no_capability_stale_flag_when_matching(tmp_path):
    _, sp = _state(tmp_path, 0.0)
    t = _transcript(tmp_path, "mid_tool_call")
    cap = _cap(tmp_path / "runaway_capability.json", "2.1.283")
    out = aw.poll(sp, transcript=t, for_s=0, now=10.0, capability_path=cap)
    assert not any(f.startswith("capability-stale") for f in out["flags"])


def test_poll_no_capability_stale_flag_when_absent(tmp_path):
    _, sp = _state(tmp_path, 0.0)
    t = _transcript(tmp_path, "mid_tool_call")
    cap = _cap(tmp_path / "runaway_capability.json", None)  # no recorded version
    out = aw.poll(sp, transcript=t, for_s=0, now=10.0, capability_path=cap)
    assert not any(f.startswith("capability-stale") for f in out["flags"])


# --- orphans: GPU hold ----------------------------------------------------------

def test_orphans_running_holds_gpu_done_does_not_other_phase_ignored(tmp_path):
    cfg = tmp_path / "projects" / "proj" / "sess" / "subagents"
    running_t, done_t = cfg / f"agent-{AGENT8}.jsonl", cfg / "agent-b0000002.jsonl"
    cfg.mkdir(parents=True, exist_ok=True)
    running_t.write_text("\n".join(json.dumps(r) for r in CASES["mid_tool_call"]) + "\n", encoding="utf-8")
    done_t.write_text("\n".join(json.dumps(r) for r in CASES["end_turn_trailing"]) + "\n", encoding="utf-8")
    ladder = tmp_path / "ladder"
    ladder.mkdir()
    aw.arm(ladder / "r.watch.json", attempt_id="r", agent_id=AGENT8, rung="local-medium",
           phase="1", router_log=None, now=0.0)
    aw.arm(ladder / "d.watch.json", attempt_id="d", agent_id="b0000002", rung="local-medium",
           phase="1", router_log=None, now=0.0)
    aw.arm(ladder / "o.watch.json", attempt_id="o", agent_id="c0000003", rung="local-medium",
           phase="2", router_log=None, now=0.0)
    for name in ("r", "d", "o"):
        aw.mark_orphan(ladder / f"{name}.watch.json")
    out = aw.orphans(ladder, phase="1", config_dir=tmp_path)
    assert out["holds_gpu"] is True
    states = {o["attempt_id"]: o["state"] for o in out["orphans"]}
    assert states == {"r": "running", "d": "done"}


# --- CLI -----------------------------------------------------------------------

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


def test_cli_poll_done_json_exit_zero(tmp_path, monkeypatch):
    state, path = _state(tmp_path, FINAL_EPOCH - 100.0)
    t = _transcript(tmp_path, "end_turn_trailing")
    _clock(monkeypatch, FINAL_EPOCH + 5.0)
    out = _cli(monkeypatch, ["poll", "--state", str(path), "--transcript", str(t),
                             "--for", "0", "--wall-s", "1000"])
    assert out["state"] == "done"
    assert out["reply_text"] == '{"claimed": "done"}'


def test_cli_poll_bad_state_path_json_exit_zero(tmp_path, monkeypatch):
    t = _transcript(tmp_path, "mid_tool_call")
    _clock(monkeypatch, 10.0)
    out = _cli(monkeypatch, ["poll", "--state", str(tmp_path / "no" / "such.json"),
                            "--transcript", str(t), "--for", "0"])
    assert isinstance(out, dict)
    assert out.get("error")


def test_cli_arm_mark_orphans(tmp_path, monkeypatch):
    cfg = tmp_path / "projects" / "proj" / "sess" / "subagents"
    cfg.mkdir(parents=True, exist_ok=True)
    t = cfg / f"agent-{AGENT8}.jsonl"
    t.write_text("\n".join(json.dumps(r) for r in CASES["mid_tool_call"]) + "\n", encoding="utf-8")
    ladder = tmp_path / "ladder"  # orphans() globs *.watch.json in this dir
    w = ladder / "a.watch.json"
    _cli(monkeypatch, ["arm", "--state", str(w), "--attempt", "a", "--agent-id", AGENT8,
                       "--rung", "local-medium", "--phase", "1"])
    _cli(monkeypatch, ["orphan-mark", "--state", str(w)])
    out = _cli(monkeypatch, ["orphans", "--dir", str(ladder), "--phase", "1",
                             "--config-dir", str(tmp_path)])
    assert out["holds_gpu"] is True
    assert out["orphans"][0]["attempt_id"] == "a"
    assert out["orphans"][0]["state"] == "running"


def test_cli_for_clamps_to_the_wait_budget(tmp_path, monkeypatch, _hermetic):
    state, path = _state(tmp_path, 0.0)
    t = _transcript(tmp_path, "mid_tool_call")
    _clock(monkeypatch, 10.0)
    out = _cli(monkeypatch, ["poll", "--state", str(path), "--transcript", str(t), "--for", "900",
                             "--wall-s", "100000"])
    assert aw.MAX_FOR_S == wait_budget.WAIT_BUDGET_S
    assert out["for_s"] == wait_budget.WAIT_BUDGET_S and out["state"] == "running"
    assert sum(_hermetic) <= wait_budget.WAIT_BUDGET_S


def test_poll_sleeps_between_reads_until_done(tmp_path, _hermetic):
    _, path = _state(tmp_path, FINAL_EPOCH - 100.0)
    t = _transcript(tmp_path, "mid_tool_call")
    clock = iter(FINAL_EPOCH - 50.0 + 15 * i for i in range(100))
    swap = []

    def fake_sleep(s):
        _hermetic.append(s)
        if len(_hermetic) == 2:  # the worker finishes during the second wait
            t.write_text("\n".join(json.dumps(r) for r in CASES["end_turn_trailing"]) + "\n",
                         encoding="utf-8")
            swap.append(s)

    out = aw.poll(path, transcript=t, for_s=120, interval_s=15, clock=lambda: next(clock),
                  sleep=fake_sleep, wall_s=1000)
    assert out["state"] == "done" and _hermetic == [15, 15] and swap


def test_poll_default_router_log_and_no_transcript_flag(tmp_path, monkeypatch):
    log = tmp_path / "router.log"
    log.write_text("", encoding="utf-8")
    monkeypatch.setenv("TP_LOCAL_LOG", str(log))
    state, path = _state(tmp_path, 0.0)
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(BUNDLES["big_end_turn"][0] + "\n")
    out = aw.poll(path, config_dir=tmp_path / "cfg", for_s=0, now=10.0, max_gen_tokens=500)
    assert out["state"] == "runaway" and "output_tokens=1000" in out["reason"]
    out = aw.poll(path, config_dir=tmp_path / "cfg", for_s=0, now=10.0)
    assert out["state"] == "running" and "watchdog-no-transcript" in out["flags"]


def test_cli_wall_s_and_max_gen_tokens_overrides(tmp_path, monkeypatch):
    state, path = _state(tmp_path, 0.0)  # router_log=None -> log_offset 0, so the line counts
    t = _transcript(tmp_path, "mid_tool_call")
    _clock(monkeypatch, 10.0)
    log = tmp_path / "router.log"
    log.write_text(BUNDLES["big_end_turn"][0] + "\n", encoding="utf-8")
    # default 24576 cap: 1000 tokens is NOT a breach -> running
    out = _cli(monkeypatch, ["poll", "--state", str(path), "--transcript", str(t),
                             "--router-log", str(log), "--for", "0", "--wall-s", "1000"])
    assert out["state"] == "running"
    # --max-gen-tokens 500: 1000 tokens becomes a breach -> runaway
    out2 = _cli(monkeypatch, ["poll", "--state", str(path), "--transcript", str(t),
                              "--router-log", str(log), "--for", "0", "--wall-s", "1000",
                              "--max-gen-tokens", "500"])
    assert out2["state"] == "runaway"
    assert "output_tokens=1000" in out2["reason"]


def test_module_has_no_subprocess():
    import ast
    tree = ast.parse((HERE / "attempt_watchdog.py").read_text(encoding="utf-8"))
    imported = [n.names[0].name for n in ast.walk(tree) if isinstance(n, ast.Import)]
    imported += [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module]
    assert "subprocess" not in imported
    for name in ("poll", "orphans", "main"):
        assert getattr(aw, name, None) is not None
