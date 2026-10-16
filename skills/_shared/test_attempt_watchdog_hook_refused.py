"""Tests for attempt_watchdog.py's hook-refusal fast catch (red-commit-hook-refusal 1.6).

A local (ceiling) rung whose transcript holds a `Red:` commit a test hook refused, with no
end-of-turn, is runaway immediately — well before the wall-clock budget. The same transcript
with an end-of-turn is `done`; a `sonnet-*` rung has no ceiling so it stays `running`; a
successful commit keeps it `running`; a generation breach still wins when both hold. The
`arm`/`CFG`/CLI idioms and the event bundles are the neighbouring `test_attempt_watchdog*.py`
files use; the record shape is the one `hook_refusal_scan` reads.
"""
from __future__ import annotations

import io
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import attempt_watchdog as aw  # noqa: E402
import router_stats as rs  # noqa: E402

BUNDLES = json.loads((HERE / "fixtures" / "attempt_watchdog" / "breach.json").read_text(encoding="utf-8"))
AGENT = "a0000001-rest-of-id"
CFG = {"attempt_wall_clock_s": 1000}

HOOK_TAIL = ("pre-commit failed\n"
             "FAILED skills/_shared/test_foo.py::test_a - AssertionError\n"
             "1 failed in 0.42s")
END_TURN_TS = "2026-10-15T10:00:00.000Z"
RED = ('git commit -m "Red: red-commit-hook-refusal 1.6 — stop at the first refused commit"')


def rec_tool_use(call_id, command, name="Bash"):
    return {"type": "assistant",
            "message": {"id": "m1", "content": [
                {"type": "tool_use", "id": call_id, "name": name, "input": {"command": command}}]}}


def rec_result(call_id, text, is_error=True):
    return {"type": "user",
            "message": {"content": [
                {"type": "tool_result", "tool_use_id": call_id, "content": text,
                 "is_error": is_error}]}}


def rec_end_turn(text='{"claimed": "green"}'):
    return {"type": "assistant", "timestamp": END_TURN_TS,
            "message": {"id": "m9", "stop_reason": "end_turn",
                        "content": [{"type": "text", "text": text}]}}


def refused_records() -> list[dict]:
    """A `Red:` commit refused by a test hook, with no end-of-turn after it."""
    return [rec_tool_use("t1", RED), rec_result("t1", HOOK_TAIL, True)]


def _arm(tmp_path, rung="local-medium", started_at=0.0, name="w") -> Path:
    path = tmp_path / "ladder" / f"1.6.{name}.watch.json"
    aw.arm(path, attempt_id="t16", agent_id=AGENT, rung=rung, phase="1",
           router_log=tmp_path / "absent-router.log", now=started_at)
    return path


def _transcript(tmp_path, records, name="agent") -> Path:
    path = tmp_path / f"{name}.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def _events(bundle_key):
    return [ev for ev in (rs.parse_line(line) for line in BUNDLES[bundle_key]) if ev]


def _verdict(tmp_path, records, rung="local-medium", started_at=0.0, bundle=None,
             now=100.0, name="w", **kw) -> dict:
    state = json.loads(_arm(tmp_path, rung, started_at, name=name).read_text(encoding="utf-8"))
    transcript = _transcript(tmp_path, records, name=name)
    return aw.verdict(state, transcript, _events(bundle) if bundle else [], CFG, now, **kw)


# --- the fast catch on a local rung -------------------------------------------

def test_refused_red_commit_is_runaway_before_the_wall_clock(tmp_path):
    out = _verdict(tmp_path, refused_records(), now=100.0)  # budget is 1000s
    assert out["state"] == "runaway", "the refused Red commit was not fast-caught at 100s"
    assert out["reason"].startswith("runaway: hook-refused: "), \
        "the fast-catch reason lacks the hook-refused prefix"
    assert "FAILED skills/_shared/test_foo.py::test_a" in out["reason"], \
        "the fast-catch reason omits the refused test path"


def test_finished_agent_with_a_refused_commit_is_done(tmp_path):
    records = refused_records() + [rec_end_turn()]
    end = datetime.fromisoformat(END_TURN_TS.replace("Z", "+00:00")).timestamp()
    out = _verdict(tmp_path, records, started_at=end - 100.0, now=end + 50.0)
    assert out["state"] == "done" and out["reason"] == ""
    assert out["reply_text"] == '{"claimed": "green"}'


def test_sonnet_rung_with_a_refused_commit_is_running(tmp_path):
    out = _verdict(tmp_path, refused_records(), rung="sonnet-xhigh", now=100.0)
    assert out["state"] == "running" and out["reason"] == ""


def test_successful_commit_is_running(tmp_path):
    records = [rec_tool_use("t1", RED),
               rec_result("t1", "[tp/x abc1234] Red: red-commit-hook-refusal 1.6", False)]
    out = _verdict(tmp_path, records, now=100.0)
    assert out["state"] == "running" and out["reason"] == ""


def test_generation_breach_wins_over_the_hook_catch(tmp_path):
    out = _verdict(tmp_path, refused_records(), bundle="max_tokens", now=100.0)
    assert out["state"] == "runaway"
    assert out["reason"] == "runaway: generation stop_reason=max_tokens output_tokens=24576"


def test_lint_only_refusal_is_running(tmp_path):
    records = [rec_tool_use("t1", RED),
               rec_result("t1", "ruff: skills/_shared/a.py:3:1: E501 line too long", True)]
    out = _verdict(tmp_path, records, now=100.0)
    assert out["state"] == "running" and out["reason"] == ""


# --- the poll / CLI path -------------------------------------------------------

@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(aw, "_sleep", lambda s: None)


def _cli(argv) -> dict:
    buf = io.StringIO()
    real = sys.stdout
    sys.stdout = buf
    try:
        rc = aw.main(argv)
    finally:
        sys.stdout = real
    assert rc == 0, "the CLI must exit 0"
    return json.loads(buf.getvalue())


def test_poll_cli_reports_the_hook_refusal(tmp_path):
    w = _arm(tmp_path, started_at=time.time())
    t = _transcript(tmp_path, refused_records())
    out = _cli(["poll", "--state", str(w), "--transcript", str(t),
                "--router-log", str(tmp_path / "absent-router.log"), "--for", "0"])
    assert out["state"] == "runaway"
    assert out["reason"].startswith("runaway: hook-refused: ")
