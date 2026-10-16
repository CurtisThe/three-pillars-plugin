"""Tests for attempt_watchdog.py on a Sonnet/Opus rung (prompt-cache-aware-dispatch 1.4).

Behaviors 1 and 6: a `sonnet-*` / `opus-*` rung is armed and polled like a local rung
but has **no runaway ceiling** — it reads only `running` or `done`, from wall clock or
from a generation breach, gets no `watchdog-no-router-stats` flag, and holds no GPU slot
so `poll` never releases one. Every case is paired with a `local-medium` control, which
is the ceiling's real subject (Behavior 6: the ladder's outcomes do not move).

The fixtures and the `arm`/`CFG` idioms are the ones `test_attempt_watchdog.py` uses.
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

BUNDLES = json.loads((HERE / "fixtures" / "attempt_watchdog" / "breach.json").read_text(encoding="utf-8"))
CASES = json.loads((HERE / "fixtures" / "transcript_tail" / "tails.json").read_text(encoding="utf-8"))["cases"]
AGENT = "a0000001-rest-of-id"
CFG = {"attempt_wall_clock_s": 1000}

FINAL_EPOCH = datetime.fromisoformat("2026-09-28T15:00:18.400Z".replace("Z", "+00:00")).timestamp()


def _arm(tmp_path, rung: str, started_at: float = 0.0, name: str = "w") -> Path:
    """arm into tmp with the given rung and return the state path."""
    path = tmp_path / "ladder" / f"1.4.{name}.watch.json"
    aw.arm(path, attempt_id="t14", agent_id=AGENT, rung=rung, phase="1",
           router_log=tmp_path / "absent-router.log", now=started_at)
    return path


def _transcript(tmp_path, case):
    path = tmp_path / "agent.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in CASES[case]) + "\n", encoding="utf-8")
    return path


def _events(bundle_key):
    return [ev for ev in (rs.parse_line(line) for line in BUNDLES[bundle_key]) if ev]


def _verdict(tmp_path, rung: str, started_at=0.0, bundle=None, case=None, now=100.0, **kw):
    state = json.loads(_arm(tmp_path, rung, started_at).read_text(encoding="utf-8"))
    transcript = _transcript(tmp_path, case) if case else None
    return aw.verdict(state, transcript, _events(bundle) if bundle else [], CFG, now, **kw)


# --- the rung name is the switch ----------------------------------------------

def test_claude_rung_names():
    assert aw.claude_rung("sonnet-xhigh") is True
    assert aw.claude_rung("opus-medium") is True
    for rung in ("local-medium", "", None):
        assert aw.claude_rung(rung) is False


# --- no wall-clock ceiling ----------------------------------------------------

def test_sonnet_rung_past_wall_clock_is_running(tmp_path):
    out = _verdict(tmp_path, "sonnet-xhigh", started_at=0.0, now=5000.0)
    assert out["state"] == "running" and out["reason"] == ""
    assert out["elapsed_s"] == 5000.0


def test_claude_rung_finished_past_budget_is_done(tmp_path):
    start = FINAL_EPOCH - 1000.0  # the fixture's final turn lands on the budget
    sonnet = _verdict(tmp_path, "sonnet-xhigh", started_at=start, case="end_turn_trailing",
                      now=FINAL_EPOCH + 1_000_000.0, finished=True)
    assert sonnet["state"] == "done" and sonnet["reason"] == ""
    assert sonnet["reply_text"] == '{"claimed": "done"}'
    control = _verdict(tmp_path, "local-medium", started_at=start, case="end_turn_trailing",
                       now=FINAL_EPOCH + 1_000_000.0, finished=True)
    assert control["state"] == "runaway"
    assert control["reason"] == "runaway: wall-clock 1000s ≥ 1000s"


def test_claude_rung_finished_without_end_turn_keeps_the_flag(tmp_path):
    out = _verdict(tmp_path, "opus-xhigh", case="mid_tool_call", now=999_999.0, finished=True)
    assert out["state"] == "done" and "watchdog-no-end-turn" in out["flags"]


# --- no generation ceiling ----------------------------------------------------

def test_opus_rung_ignores_generation_breach(tmp_path):
    opus = _verdict(tmp_path, "opus-xhigh", bundle="max_tokens", now=100.0)
    assert opus["state"] == "running" and opus["reason"] == ""
    control = _verdict(tmp_path, "local-medium", bundle="max_tokens", now=100.0)
    assert control["state"] == "runaway"
    assert control["reason"] == "runaway: generation stop_reason=max_tokens output_tokens=24576"


# --- the flags a Claude rung never gets ---------------------------------------

def test_claude_rung_done_returns_reply(tmp_path):
    out = _verdict(tmp_path, "sonnet-medium", case="end_turn_trailing", now=FINAL_EPOCH)
    assert out["state"] == "done" and out["reason"] == ""
    assert out["reply_text"] == '{"claimed": "done"}'
    assert "watchdog-no-router-stats" not in out["flags"]


def test_local_control_without_router_stats_keeps_the_flag(tmp_path):
    out = _verdict(tmp_path, "local-medium", case="end_turn_trailing", now=100.0)
    assert out["flags"] == ["watchdog-no-router-stats"]


# --- poll: a done Claude rung holds no slot to release ------------------------

@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(aw, "_sleep", lambda s: None)


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake(agent_id):
        seen.append(agent_id)
        return "released"

    monkeypatch.setattr(aw, "_release", fake)
    return seen


def _poll(tmp_path, rung: str, calls, name: str = "w") -> dict:
    w = _arm(tmp_path, rung, started_at=FINAL_EPOCH - 100.0, name=name)
    return aw.poll(w, transcript=_transcript(tmp_path, "end_turn_trailing"),
                   router_log=tmp_path / "absent-router.log", finished=True,
                   capability_path=tmp_path / "absent-capability.json")


def test_poll_done_on_claude_rung_skips_release(tmp_path, calls):
    out = _poll(tmp_path, "sonnet-xhigh", calls)
    assert out["state"] == "done"
    assert "release" not in out
    assert calls == []
    control = _poll(tmp_path, "local-medium", calls, name="control")
    assert control["state"] == "done" and control["release"] == "released"
    assert calls == [AGENT]


# --- the CLI path arms and polls a Sonnet rung --------------------------------

def _cli(argv):
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


def test_cli_arm_and_poll_sonnet(tmp_path, calls):
    w = tmp_path / "ladder" / "1.4.cli.watch.json"
    t = _transcript(tmp_path, "end_turn_trailing")
    absent = str(tmp_path / "absent-router.log")
    armed = _cli(["arm", "--state", str(w), "--attempt", "a1", "--agent-id", AGENT,
                  "--rung", "sonnet-medium", "--phase", "1", "--router-log", absent])
    assert armed["rung"] == "sonnet-medium"
    out = _cli(["poll", "--state", str(w), "--transcript", str(t),
                "--router-log", absent, "--for", "0"])
    assert out["state"] == "done"
    assert out["reply_text"] == '{"claimed": "done"}'
    assert "release" not in out and calls == []
